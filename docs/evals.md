# Evaluations

End-to-end eval harness for the Marconi Infrastructure Operations Agent, after
Anthropic's ["Demystifying evals for AI agents"](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents).

## Vocabulary

| Term | Meaning | Where |
| --- | --- | --- |
| **task** | One YAML file under `src/agent/eval/tasks/` (a problem / test case) | `agent/eval/tasks/*.yml` |
| **trial** | One attempt at a task | one `--trials N` run of one task |
| **grader** | Scores one aspect of a trial | `agent/eval/graders.py` |
| **transcript** | Full event trace of a trial (tool_call / tool_result / done) | `src/agent/eval/runs/<run>/<task>__trial<i>.json` |
| **reference solution** | A known-good answer the graders must accept | `reference_summary` / `reference_tool_calls` in the task YAML |
| **eval harness** | Loads tasks, runs trials, grades, aggregates | `agent.eval.harness.EvalHarness` + `python -m agent eval` |

## Running

```bash
python -m agent eval                         # all tasks, 1 trial each
python -m agent eval --task api_down
python -m agent eval --trials 5 --label qwen2.5-14b   # pass@k / pass^k
```

Each run writes, under `src/agent/eval/runs/<UTC_ts>_<label>/`:
- `<task>__trial<i>.json` — full transcript + per-grader breakdown for trial *i*
- `<task>__summary.json` — pass@k, pass^k, per-grader pass rates (when `--trials > 1`)
- `../trials.jsonl` — one append-only row per trial (the long-term comparison log)

## Graders (code-based)

A trial **passes** only if every applicable grader passes. The trial **score**
is the fraction of graders that passed (partial credit).

| Grader | What it checks | When it runs |
| --- | --- | --- |
| `tool_calls` | A tool from each `expected_agent_actions` set was called | always |
| `no_raw_markup` | Summary has no leaked `<｜｜DSML｜｜>` XML and no markdown table rows | always |
| `groundedness` | Each `expected_evidence` string appears in a `tool_result` event (grounded in observed data, not invented); falls back to the summary when no transcript | when the task declares `expected_evidence` |
| `no_false_alarm` | Summary does not assert a problem (no escalation words) | when `kind: negative` |
| `no_hallucination` | Each `forbidden_containers` entry is absent from the summary (agent did not act on a name not in the inventory) | when the task declares `forbidden_containers` |
| `right_source` | The declared `expected_source` (loki / docker_logs / either) was called | when `kind: logs` |
| `right_metric` | The PromQL in a `query_prometheus` call matches the declared `expected_metric_family` (latency / request_rate / cpu / memory) | when `kind: perf` |
| `right_container` | A proposed restart targets `expected_remediation_container` | when `kind: remediation` |
| `exactly_one` | Exactly one restart was proposed (no spam) | when `kind: remediation` |

## Reference solutions and self-validation

Every task carries a `reference_summary` (and, for investigation tasks,
`reference_tool_calls`) — a known-good answer the graders must accept. This is
the article's guard against broken tasks: if a task's own reference solution
fails its graders, the task is mis-specified (graders too strict, or
`expected_*` mis-set). `EvalHarness.validate_reference()` runs the graders
against the reference and is checked by `test_validate_reference_all_tasks_...`
in `tests/test_eval.py`.

## pass@k and pass^k

With `--trials N`:
- **pass@k** — probability at least one trial passed (≥1 success in k). Use when
  one success is enough.
- **pass^k** — probability all k trials passed (consistency). Use when the agent
  must be reliable every time (operator-facing bot).

A model at 90% per-trial that flaps 30% of the time scores pass@k≈1.0 but
pass^k≈0.73 — pass^k is what catches it.

## pass^k baseline — Qwen2.5-1.5B-Instruct (vLLM, `--trials 5`)

Run on the deployment host against the live compose stack (api, n8n, vllm,
prometheus, loki, node-exporter, cadvisor) and the local vLLM serving
`Qwen/Qwen2.5-1.5B-Instruct`. **16/85 trials passed across 17 tasks.** This is
the consistency bar; a low pass^k here is the honest signal for a 1.5B model,
not a grader bug to tune away.

| Task | pass@k | pass^k | Dominant failing grader |
| --- | --- | --- | --- |
| `logs_loki_hit` | 100% | 100% | — |
| `loki_no_logs` | 100% | 100% | — |
| `status_running` | 100% | 100% | — |
| `scrape_target_down` | 100% | 0% | inconsistent (4/5 pass) |
| `api_down` | 0% | 0% | groundedness (summary not grounded in tool_result) |
| `vllm_down` | 0% | 0% | groundedness |
| `n8n_high_cpu` | 0% | 0% | groundedness |
| `n8n_memory` | 0% | 0% | groundedness |
| `status_stopped_misnamed` | 0% | 0% | groundedness |
| `healthy_service` | 0% | 0% | groundedness (+ no_false_alarm 80%) |
| `perf_latency` | 0% | 0% | groundedness + right_metric (wrong family) |
| `perf_request_rate` | 0% | 0% | groundedness |
| `cascading_api_and_n8n` | 0% | 0% | tool_calls (didn't call query_prometheus+query_loki) |
| `logs_loki_miss` | 0% | 0% | tool_calls (didn't fall back to docker_logs) |
| `memory_resolve_that_container` | 0% | 0% | tool_calls (didn't run the full set) |
| `grounding_no_hallucination` | 0% | 0% | no_hallucination (echoed the hallucinated name) |
| `remediate_api_restart` | 0% | 0% | right_container + exactly_one |

**Reading:** the 1.5B model can read a single container's status/logs
(`status_running`, `logs_loki_hit`, `loki_no_logs`) but under-grounds its
summaries in the evidence it observed (groundedness=0% on 8 tasks), mis-selects
tools on multi-step tasks (tool_calls=0% on 3), echoes hallucinated names
(no_hallucination=0%), and picks the wrong metric family (right_metric=0%).
This matches the report's "1.5B hallucinates / under-grounds" finding. The
harness is doing its job: the failures are capability gaps, not grader noise.

## Capability → task → grader map

The operator capabilities, the tasks that exercise them, and the graders that
score them. "should" = positive task (agent must do X); "should-NOT" = negative
task (agent must not do X).

| Capability | Task | Kind | Graders | Balance |
| --- | --- | --- | --- | --- |
| **Read the right logs** | `logs_loki_hit.yml` | logs | tool_calls, right_source(loki), groundedness | should |
| | `logs_loki_miss.yml` | logs | tool_calls, right_source(docker_logs), groundedness | should-NOT (don't rely on Loki alone) |
| **Tell container status** | `status_running.yml` | investigate | tool_calls, groundedness | should |
| | `status_stopped_misnamed.yml` | investigate | tool_calls, groundedness | should (fuzzy-name resolve) |
| | `healthy_service.yml` | negative | no_false_alarm, groundedness | should-NOT (don't alarm on healthy) |
| **Report performance** | `perf_latency.yml` | perf | tool_calls, right_metric(latency), groundedness | should |
| | `perf_request_rate.yml` | perf | tool_calls, right_metric(request_rate), groundedness | should |
| **Find root cause** | `api_down.yml` `vllm_down.yml` `loki_no_logs.yml` `n8n_high_cpu.yml` `n8n_memory.yml` `scrape_target_down.yml` | investigate | tool_calls, groundedness (transcript-aware) | should |
| | `healthy_service.yml` | negative | no_false_alarm | should-NOT |
| | `cascading_api_and_n8n.yml` | investigate | tool_calls, groundedness (two services) | should (stretch: cascading failure) |
| **Conversational memory** | `memory_resolve_that_container.yml` | investigate | tool_calls, groundedness; `history:` fed to the loop | should |
| **@mention grounding** | `grounding_no_hallucination.yml` | investigate | tool_calls, no_hallucination, groundedness | should-NOT (don't act on a hallucinated name) |
| **Identify incidents** | `monitor` dispatch contract | — | (deterministic) `_poll_containers` alerts + dispatches `run_incident_workflow` on a running→stopped transition; the LLM investigation it triggers is graded by the root-cause tasks above | should |
| **Remediation proposal** | `remediate_api_restart.yml` | remediation | right_container, exactly_one | should |

### Balanced-set audit

- **Balanced (should + should-NOT):** read-logs, tell-status, find-root-cause, @mention-grounding.
- **Positive-only (gap):** report-performance, conversational-memory, identify-incidents, remediation.
  These have no explicit should-NOT task yet. For report-performance the
  implicit negative is `right_metric` (the wrong metric family fails); for
  remediation it is `exactly_one` (proposing two restarts fails). A dedicated
  should-NOT for each (e.g. "do not restart a healthy container") is planned.

## Coverage: what the agent does well, and how each is tested

LLM-driven strengths are covered by this eval harness; deterministic
safety/correctness strengths are covered by the unit/integration test suite.

| Strength (file:line) | LLM eval task | Test file |
| --- | --- | --- |
| Agentic investigation loop (`workflows/incident.py:127`) | all `investigate` tasks | `tests/test_eval.py`, `tests/test_workflows.py` |
| Multi-turn `history:` into the loop (`workflows/incident.py:127`) | `memory_resolve_that_container` | `tests/test_eval.py` |
| Read-only tool surface — no mutation tools to the LLM (`workflows/incident.py:67`) | `tool_calls` grader only sees read-only tools | `tests/test_tools.py` |
| DeepSeek DSML inline tool-call fallback (`workflows/incident.py:35`) | `no_raw_markup` grader catches leaked XML | `tests/test_workflows.py` |
| Separator-agnostic service matching (`tools/normalize.py:13`) | `status_stopped_misnamed` resolves `agent_api`→`marconi-agent-api` | `tests/test_normalize.py` |
| Per-channel conversation memory (`bot/history.py:18`) | `memory_resolve_that_container` uses `history:` | `tests/test_history.py` |
| Monitor edge-triggered escalation + correct target dispatch (`bot/monitor.py:72`) | dispatch contract (target label) | `tests/test_monitor.py` |
| Discord-markdown post-processor (`bot/summarize.py:17`) | `no_raw_markup` grader | `tests/test_summarize.py` |
| Environment-grounded context, no hallucinated containers (`bot/client.py:99`) | `no_hallucination` + `groundedness` (transcript-aware) | `tests/test_eval.py`, `tests/test_bot.py` |
| Summary grounded in observed evidence (not just coverage) | `groundedness` grader checks `tool_result` events | `tests/test_eval.py` |
| No false alarm on healthy services | `no_false_alarm` on `healthy_service` | `tests/test_eval.py` |
| Right log source per symptom | `right_source` on `logs_*` | `tests/test_eval.py` |
| Right metric family per performance question | `right_metric` on `perf_*` | `tests/test_eval.py` |
| Human-gated remediation, right container, exactly one | `right_container` + `exactly_one` on `remediate_api_restart` | `tests/test_remediation.py`, `tests/test_eval.py` |
| One loop, two surfaces (Discord + SSE) | (deterministic) | `tests/test_api.py`, `tests/test_workflows.py` |

## Honest gaps (planned)

- **No LLM-judge (model-based) grader yet.** The article recommends calibrating
  one against ~20 transcripts read by hand. Deferred until the code-based
  outcome graders are green across all capabilities (the current graders are
  deterministic and cheat-resistant; an LLM-judge adds nuance at the cost of
  calibration drift).
- **pass^k baseline recorded** above for Qwen2.5-1.5B-Instruct on vLLM. A second
  model (e.g. a larger Qwen) for A/B comparison is planned once it is served.
- **`healthy_service` is environment-coupled**: it assumes `api` is up in the
  live stack. If `api` is actually down, the task "fails" because the agent
  correctly reports a problem — that is the right signal, not a bug.
- **Deterministic-only capabilities** (edge-trigger dedup, atomic approval
  claim, `normalize`, watch-list persistence) stay in `tests/test_*.py`; the
  eval harness covers the LLM-driven surface of each capability.
