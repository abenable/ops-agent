# Evaluations

End-to-end eval harness for the Marconi Infrastructure Operations Agent, after
Anthropic's ["Demystifying evals for AI agents"](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents).

## Vocabulary

| Term | Meaning | Where |
| --- | --- | --- |
| **task** | One YAML file under `tasks/` (a problem / test case) | `tasks/*.yml` |
| **trial** | One attempt at a task | one `--trials N` run of one task |
| **grader** | Scores one aspect of a trial | `agent/eval/__init__.py` |
| **transcript** | Full event trace of a trial (tool_call / tool_result / done) | `eval_runs/<run>/<task>__trial<i>.json` |
| **eval harness** | Loads tasks, runs trials, grades, aggregates | `agent.eval.EvalHarness` + `python -m agent eval` |

## Running

```bash
python -m agent eval                         # all tasks, 1 trial each
python -m agent eval --task tasks/api_down.yml
python -m agent eval --trials 5 --label qwen2.5-14b   # pass@k / pass^k
```

Each run writes, under `eval_runs/<UTC_ts>_<label>/`:
- `<task>__trial<i>.json` — full transcript + per-grader breakdown for trial *i*
- `<task>__summary.json` — pass@k, pass^k, per-grader pass rates (when `--trials > 1`)
- `../trials.jsonl` — one append-only row per trial (the long-term comparison log)

## Graders (code-based)

| Grader | What it checks | When it runs |
| --- | --- | --- |
| `tool_calls` | A tool from each `expected_agent_actions` set was called | always |
| `no_raw_markup` | Summary has no leaked `<｜｜DSML｜｜>` XML and no markdown table rows | always |
| `groundedness` | Each `expected_evidence` string appears in the summary (coverage) | when the task declares `expected_evidence` |
| `no_false_alarm` | Summary does not assert a problem (no escalation words) | when `kind: negative` |

A trial **passes** only if every applicable grader passes. The trial **score**
is the fraction of graders that passed (partial credit).

## pass@k and pass^k

With `--trials N`:
- **pass@k** — probability at least one trial passed (≥1 success in k). Use when
  one success is enough.
- **pass^k** — probability all k trials passed (consistency). Use when the agent
  must be reliable every time (operator-facing bot).

A model at 90% per-trial that flaps 30% of the time scores pass@k≈1.0 but
pass^k≈0.73 — pass^k is what catches it.

## Tasks

| File | Kind | Service | What it exercises |
| --- | --- | --- | --- |
| `tasks/api_down.yml` | investigate | api | Container stopped; calls list_services, docker_status, docker_logs, query_prometheus; summary names `api` + `stopped` |
| `tasks/loki_no_logs.yml` | investigate | n8n | Missing logs in Loki; falls back to docker_logs on promtail |
| `tasks/n8n_high_cpu.yml` | investigate | n8n | CPU metric discovery + docker_logs |
| `tasks/n8n_memory.yml` | investigate | n8n | Memory metric + OOM trend |
| `tasks/scrape_target_down.yml` | investigate | node-exporter | PromQL up=0; metric/label discovery |
| `tasks/vllm_down.yml` | investigate | vllm | Endpoint unreachable; summary names `vllm` + `unreachable` |
| `tasks/healthy_service.yml` | negative | api | **Balanced problem set**: a healthy service. The agent must confirm health and NOT raise a false incident (`no_false_alarm` grader) |

## Coverage: what the agent does well, and how each is tested

The strengths identified in the codebase review, mapped to where they are
verified. LLM-driven strengths are covered by this eval harness; deterministic
safety/correctness strengths are covered by the unit/integration test suite.

| Strength (file:line) | LLM eval task | Test file |
| --- | --- | --- |
| Agentic investigation loop (`workflows/incident.py:127`) | all `investigate` tasks | `tests/test_eval.py`, `tests/test_workflows.py` |
| Read-only tool surface — no mutation tools to the LLM (`workflows/incident.py:67`) | `tool_calls` grader only sees read-only tools | `tests/test_tools.py` |
| DeepSeek DSML inline tool-call fallback (`workflows/incident.py:35`) | `no_raw_markup` grader catches leaked XML | `tests/test_workflows.py` |
| Separator-agnostic service matching (`tools/normalize.py:13`) | (deterministic) | `tests/test_normalize.py` |
| Per-channel conversation memory (`bot/history.py:18`) | (deterministic) | `tests/test_history.py` |
| Monitor edge-triggered escalation (`bot/monitor.py:176`) | (deterministic) | `tests/test_monitor.py` |
| Discord-markdown post-processor (`bot/summarize.py:17`) | `no_raw_markup` grader | `tests/test_summarize.py` |
| Environment-grounded context, no hallucinated containers (`bot/client.py:99`) | `groundedness` + `tool_calls` (calls list_services) | `tests/test_bot.py` |
| Summary grounded in evidence (coverage) | `groundedness` grader | `tests/test_eval.py` |
| No false alarm on healthy services | `no_false_alarm` grader on `healthy_service` | `tests/test_eval.py` |
| Human-gated remediation, atomic claim (`workflows/remediation.py:47`) | (deterministic; not LLM-exposed) | `tests/test_remediation.py` |
| One loop, two surfaces (Discord + SSE) | (deterministic) | `tests/test_api.py`, `tests/test_workflows.py` |

## Honest gaps (planned)

- `groundedness` checks evidence appears in the *summary* (coverage). A
  stronger groundedness check — evidence appears in a `tool_result` event in
  the transcript — is the next step; it needs the transcript passed to the
  grader.
- No LLM-judge (model-based) grader yet. The article recommends calibrating one
  against ~20 transcripts read by hand.
- The `healthy_service` negative task is environment-coupled: it assumes `api`
  is up in the live stack. If `api` is actually down, the task "fails" because
  the agent correctly reports a problem — that is the right signal, not a bug.
