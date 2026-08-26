# Evaluation

`eval/` holds notebooks that measure how the model behaves on each backend, and
a shared harness that records every run.

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
| `08_all_tools` | all ten, through the real agent |

`01` through `07` each bind one backend and ask two questions: one the tools can
answer, and one they cannot. The second is the interesting one, because it
measures whether the model admits the limit or hallucinates past it.

`08` is different. It imports the production agent (`from agent.agent import
get_agent`) and drives it with memory, so it tests which tool the model reaches
for when nothing is taken away, and whether context carries across turns on a
thread.

Run them from `eval/`. The kernel's working directory is what makes
`from eval_transcript import run_eval_loop` resolve.

## The harness

`eval/eval_transcript.py` runs a question against a tool set and records
everything:

```python
answer = await run_eval_loop(
    "04_query_prometheus:live", TOOLS, SYSTEM_PROMPT,
    "What is the current value of the 'up' metric?",
    expect=["node-exporter"],          # optional
)
```

Every run writes `eval/logs/<timestamp>__<label>.json` containing each turn's
sent messages, the response, tool calls and results, per-call token usage and
duration, and the grade.

The dump is in a `finally`, so a run that dies from an endpoint 500, a context
overflow, or a timeout still leaves the turns it completed, with the error
recorded. Those are usually the runs worth reading.

`run_eval_repeats(..., runs=3)` asks the same question several times and reports
how many passed and how many distinct answers came back. One sample proves
nothing: temperature 0 is not a determinism guarantee on any of these providers.

## Grading

`expect` is a list of substrings the answer must contain. This is deliberately crude,
since a substring list is not a rubric. It catches the failure mode worth
catching automatically: a fluent, well-structured answer that never mentions the
dominant evidence at all. Whether what it *did* say is correct is still a human
read of the transcript.

## Budget semantics

The harness counts `MAX_TOOL_STEPS` as **tool calls**, matching production's
`ToolCallLimitMiddleware(run_limit=...)`. A call that would exceed the budget is
not executed, nor are its siblings on the same message.

Transcripts record both `tool_calls` (actually dispatched) and
`tool_calls_requested` (what the model asked for, the budget unit); an
unavailable tool or a budget-blocked call spends budget without running.

One deliberate difference from production: after the budget is spent the harness
makes one extra call asking the model to summarize what it found, so the
transcript captures a conclusion. Production simply ends. That turn is tagged
`"tool-call-budget summary (harness-added; production ends here instead)"`.

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

`tests/test_eval_transcript.py` covers the loop itself: budget counting, the
crash-path transcript, unknown tool names, and grading. It runs against a fake
model with transcripts redirected to `tmp_path`.
