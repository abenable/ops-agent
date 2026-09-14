# Evaluation

`eval/` holds notebooks that measure how the model behaves on each backend, a
shared harness that records every run, and the tooling to run the whole suite
against two models and compare them.

## The notebooks

| Notebook | Bound tools |
|---|---|
| `01_list_services` | `list_services` |
| `02_docker_status` | `docker_status` |
| `03_docker_logs` | `docker_logs` |
| `04_query_prometheus` | `list_metric_names`, `get_label_values`, `query_prometheus` |
| `05_query_prometheus_range` | as above, with `query_prometheus_range` |
| `06_query_loki` | `get_loki_label_values`, `query_loki` |
| `07_query_loki_range` | `get_loki_label_values`, `query_loki_range` |
| `08_all_tools` | all configured tools, through the real production agent |

`01` through `07` each bind one backend and ask two questions: one the tools can
answer, and one they cannot. The second is the interesting one, because it
measures whether the model admits the limit or hallucinates past it.

`08` is different. It imports the production agent (`from agent.agent import
get_agent`) and drives it with memory. It asks a broad question, then a
follow-up naming nothing (`resume=True` — the one place a thread is continued on
purpose), then repeats that follow-up on a fresh thread, which should fail,
demonstrating isolation.

Run them from `eval/`. The kernel's working directory is what makes
`from eval_transcript import run_agent_eval` resolve.

## The harness

`eval/eval_transcript.py` runs one question against a tool set through the real
agent and records everything:

```python
answer = await run_agent_eval(
    "04_query_prometheus:live-inscope",
    "What is the current value of the 'up' metric?",
    thread_id="04_query_prometheus:live-inscope",
    tools=TOOLS,              # None means every configured tool
    resume=False,             # True continues the thread a previous call created
)
```

Every run writes `eval/logs/<model>/<timestamp>__<label>.json` — one
subdirectory per model — containing the system prompt, the bound tools, each
turn's response with tool calls (including call ids) and results, per-turn
token usage, and duration. `print_summary()` prints one row per transcript
across all model directories.

Threads are isolated by default: the harness suffixes a unique run id onto the
caller's `thread_id`, so re-running a case can never replay a previous
conversation into the model's context. `resume=True` opts back into the thread
a previous call with the same `thread_id` argument created — that is how the
`08` memory case works.

A run that dies mid-invoke still writes a transcript, with the exception in
`error`. An exhausted endpoint does not raise at all — `ModelRetryMiddleware`
returns "Model call failed after N attempts" as the answer — so that answer is
recorded in `error` too. Without it a dead model scores as a clean, cheap,
zero-tool run. Those are the runs worth reading.

There is deliberately no automated grading in the harness. A substring check
catches only the crudest failure, and the interesting failure modes — a
hallucinated tool name, a health verdict with no evidence, an empty answer —
need a human read of the transcript. `eval/manual_qa_eval.md` is the rubric.

## Running the whole suite

`eval/run_suite.py` executes every notebook's cases in one process, on whatever
model the environment selects, exactly like production:

```bash
cd eval
LLM_PROVIDER=google LLM_MODEL=gemma-4-31b-it python run_suite.py --runs 3
LLM_PROVIDER=openai LLM_MODEL=marconi-llm python run_suite.py --runs 3   # the proxy
```

`--runs N` repeats every case N times (default 1), each repetition on its own
thread. A trailing label substring filters cases: `python run_suite.py 06 07`.

`eval/analyze.py <model> [<model> ...]` reads the transcripts and prints a
per-case comparison averaged over every run of that case, per-model averages
(valid vs hallucinated calls, errored runs, tokens, duration), and tokens per
tool — the calling turn's cost plus the next turn's input, which carries the
tool result. It is how the Loki tools were identified as the dominant token
sink.

Current results and conclusions: `docs/model-comparison-20260913.md` (2 runs
per case, 68 runs) for the model choice, and
`docs/tool-and-task-performance-20260913.md` for per-tool cost, tool failure
root causes, and which shapes of task are actually hard. The earlier `docs/model-comparison-20260827.md` ran one
sample per case and is superseded — several of its conclusions do not survive a
second run. Temperature 0 is not a determinism guarantee on any of these
providers, so use `--runs 2` at minimum.

## Budget semantics

The budget is production's: `ToolCallLimitMiddleware(run_limit=settings.max_tool_steps,
exit_behavior="end")` — 20 tool calls by default, `MAX_TOOL_STEPS` to change it —
counts tool calls and ends the run when it is exhausted.
The transcript records the limit message as the final turn, which is also what
an operator would see. Both models in the comparison reached the limit on
"check everything" questions — see the comparison report's recommendations
before raising it.

## Offline dataset

`scripts/build_eval_dataset.sh` and its helpers dump real metrics and logs into
`data/eval/*.jsonl`. `agent/tools/helper.py` exposes them as
`query_eval_metrics` and `query_eval_logs`, so notebooks can generate and test
tasks against captured data without live infrastructure.

## Manual QA

`eval/manual_qa_eval.md` is the end-to-end pass the notebooks cannot cover: the
agent answering through Discord, with memory and formatting in play. Each entry
pairs a question — asked by DM or mention for the conversational ones, by slash
command for the rest — with a reference answer computed by calling the same tool
functions directly against the same live state.

The questions cover factual correctness, behaviour when a backend is down,
per-channel memory, tool-call economy, and whether the agent admits what falls
outside its scope. References are pinned to a dated infrastructure snapshot
recorded at the top of the file. State drifts, so a mismatch is a prompt to
recheck the tool call behind the reference rather than an automatic failure.

## Staged scenarios

The notebooks and the manual pass both read whatever state the lab happens to be
in. `scripts/run_scenario.py` instead *creates* the state it wants, which is the
only way to test a fault that is not currently happening:

```bash
uv run python scripts/run_scenario.py             # both scenarios
uv run python scripts/run_scenario.py healthy     # one
uv run python scripts/run_scenario.py container_down --keep
```

It starts a disposable `marconi-scenario-target` container, optionally stops it,
asks the agent whether that container is healthy, and grades the answer. Results
land in `eval/results/scenarios/`, and go to `DISCORD_TEST_SCENARIOS_CHANNEL_ID`
when one is configured. Cleanup runs in a `finally`, so a crashed run does not
leave the container behind; `--keep` opts out for debugging.

Two scenarios, and the second is the important one:

| Scenario | Staged state | Passes when |
|---|---|---|
| `container_down` | container stopped | the agent says exited / stopped / not running |
| `healthy` | container running | the agent says running / up, and does **not** say exited |

`healthy` is the control. Without it, an agent that answered "something is down"
to every question would score full marks on the fault scenario. Testing only the
failure case measures nothing, because the trivially broken agent passes it.

This script creates and stops containers, so it is deliberately not an agent
tool and lives in `scripts/`. The read-only guarantee is that no such call
exists in the tool table — putting a mutating call there to make testing easier
would remove the property the tests are meant to protect.

## Testing the harness

`tests/test_eval_transcript.py` covers the loop itself: message serialisation
and reasoning extraction, usage accounting, and that `run_agent_eval` drives
the real agent, defaults to the configured tool set, and measures only the new
turns of a reused thread.
