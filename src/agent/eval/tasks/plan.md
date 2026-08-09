# Implementation Plan: Capability-graded evals for the Marconi ops agent

## Overview

Build evals for each **operator capability** the agent claims to do well — read
logs, tell container status, identify incidents, find root cause, report
performance — plus the secondary operator-facing capabilities (conversational
`/ask`/@mention, `/task` simulation, human-gated remediation proposals). Today
the harness grades the *agentic investigation loop* on 6 services + one
negative task. It does **not** grade: the monitor's auto-incident path,
multi-turn memory, @mention grounding, latency/request-rate reporting, or
remediation proposals. The plan closes those gaps and upgrades path-based
grading to outcome-based grading per Anthropic's eval guidance.

The output target: an eval suite where every capability has at least one
positive task ("should do X"), one negative task ("should NOT do X"), an
outcome grader (checks the *right* tool/query was chosen, not just any), a
reference solution that proves the graders pass, and a pass^k consistency bar
recorded in `trials.jsonl`.

## Architecture decisions

1. **Grade outcomes, not paths.** The current `tool_calls` grader accepts any
   tool from an action's set. Add per-capability outcome graders that inspect
   the *transcript* (tool args + tool results), not just tool names. This
   requires passing the transcript to `EvalHarness.evaluate`.
2. **Transcript-aware graders.** `groundedness` upgrades from "evidence in
   summary" to "evidence in a `tool_result` event". Add `no_hallucination`
   (summary only names containers that appear in a `list_services` result) and
   `right_source` (the right log source — Loki vs `docker_logs` — for the
   symptom).
3. **Multi-turn support in the harness.** Add an optional `history:` field to
   task YAML and pass it to `run_agentic_investigation_stream(..., history=...)`
   so memory and @mention-grounding can be evaluated.
4. **Deterministic vs LLM-eval split stays explicit.** Pure-mechanism
   capabilities (edge-trigger dedup, atomic approval claim, `normalize`
   matching, watch-list persistence) stay in `tests/test_*.py`. The eval
   harness covers the LLM-driven surface of each capability.
5. **Reference solutions per task.** Every task gets `reference_summary` +
   `reference_tool_calls`; `EvalHarness.validate_reference()` proves the
   graders pass on a known-good transcript (catches broken tasks, per the
   article's "0% pass@100 = broken task" guidance).
6. **No new framework.** Reuse `agent/eval`, `python -m agent eval`, and
   `trials.jsonl`. The article's own closing advice: invest in the evals, not
   the framework.

## Capability → eval gap map (what this plan closes)

| Capability | Today | Gap to close |
| --- | --- | --- |
| Find the root cause | 6 tasks, path-graded | Upgrade to outcome-graded (evidence in `tool_result`); add reference solutions |
| Tell container status | partial (`healthy_service`, `api_down`) | Add "report correct state" + "don't hallucinate state" tasks; `no_hallucination` grader |
| Read container logs | `loki_no_logs` | Add `right_source` grader; tasks for each source path (Loki hit, Loki miss → docker_logs) |
| Identify incidents (monitor) | none (deterministic tests only) | Integration eval: down transition → incident opened → investigation summary graded |
| Report performance | CPU + memory only | Add latency + request-rate tasks; grader for the right metric family |
| Conversational `/ask`/@mention | none | Multi-turn task support; "resolve *that container* from history" task |
| @mention grounding | none | Task with a hallucinated container name; `no_hallucination` grader |
| Remediation proposals | none (deterministic only) | Eval: does the remediation agent propose the right restart for the right incident |

## Task list

### Phase 1: Grader infrastructure (foundation)

- [ ] **T1. Pass transcript to `evaluate`; outcome-grader base.** Add
  `transcript: list[dict]` param to `EvalHarness.evaluate`; thread it into
  graders. Keep backward compat (old callers still work). Size: S.
- [ ] **T2. Upgrade `groundedness` to check `tool_result`s.** When
  `expected_evidence` is declared, require each evidence string to appear in
  a `tool_result` event (not just the summary). Keep summary-check as a
  weaker secondary signal. Size: S.
- [ ] **T3. Add `no_hallucination` grader.** Extract every container name the
  summary mentions; require each to appear in a `list_services` or
  `docker_status` `tool_result`. Runs on all tasks. Size: S.
- [ ] **T4. Add `right_source` grader (logs).** For `kind: logs` tasks, check
  the right source was called with the right container per the task's
  `expected_source` field (loki | docker_logs | either). Size: S.
- [ ] **T5. Add multi-turn task support.** Optional `history:` field in task
  YAML (list of `{role, content}` turns); CLI passes it to
  `run_agentic_investigation_stream(..., history=...)`. Size: M.

### Checkpoint: Foundation
- [ ] `uv run pytest tests/test_eval.py` green
- [ ] `python -m agent eval --task tasks/loki_no_logs.yml` still passes with
  the new transcript-aware graders
- [ ] No regression in the 7 existing tasks

### Phase 2: Capability eval suites (vertical slices)

- [ ] **T6. "Read the right logs" suite.** 2 tasks: `logs_loki_hit`
  (symptom → Loki has the logs → `query_loki`), `logs_loki_miss`
  (symptom → Loki empty → `docker_logs` on promtail). Grader: `right_source`.
  Reference solutions. Size: M.
- [ ] **T7. "Tell container status" suite.** 2 tasks: `status_running` (must
  report running + not alarm), `status_stopped_misnamed` (operator's fuzzy
  name → right container → stopped). Negative: `status_healthy_no_alarm`.
  Graders: `no_hallucination`, `no_false_alarm`, `groundedness`. Size: M.
- [ ] **T8. "Report performance" suite.** 2 tasks: `perf_latency` (symptom →
  histogram_quantile latency), `perf_request_rate` (symptom →
  rate(http_requests_total[5m])). Grader: the right metric family queried
  (regex on the PromQL in the transcript). Size: M.
- [ ] **T9. Upgrade "find root cause" suite to outcome grading.** Add
  `reference_summary` + `expected_evidence` to the 6 existing tasks; flip
  `groundedness` to check `tool_result` (T2). Add one harder cascading-failure
  task (two services down) as a capability stretch. Size: M.
- [ ] **T10. "Conversational memory" task.** `memory_resolve_that_container`:
  turn 1 establishes service X, turn 2 says "investigate *that one*".
  Grader: turn-2 `docker_status`/`query_loki` args reference service X.
  Depends on T5. Size: M.
- [ ] **T11. "@mention grounding" task.** `grounding_no_hallucination`: prompt
  names a non-existent container; agent must call `list_services` first and
  not act on the hallucinated name. Graders: `no_hallucination`,
  `tool_calls` (list_services called first). Size: S.
- [ ] **T12. "Identify incidents" integration eval.** Drive a mocked down
  transition through `bot/monitor`'s detection → incident-open path; grade
  that an incident is created, a thread is opened, and the investigation
  summary passes `groundedness`. New harness entry point
  (`run_monitor_eval`). Size: L → split if it touches >5 files.
- [ ] **T13. "Remediation proposal" eval.** Task: given an incident summary,
  does the remediation agent propose the right restart for the right
  container, and only one? Grader: `propose_restart` called once with the
  right container, no execute. Drives `workflows/remediation.py` directly.
  Size: M.

### Checkpoint: Capability suites
- [ ] Every capability in the gap map has ≥1 positive + ≥1 negative task
- [ ] `python -m agent eval` runs all tasks; trials.jsonl records per-grader
  pass rates
- [ ] `uv run pytest -q` green (deterministic tests unchanged)

### Phase 3: Article-aligned hardening

- [ ] **T14. Reference solutions + `validate_reference()`.** Add
  `reference_summary` + `reference_tool_calls` to every task; add
  `EvalHarness.validate_reference()` that runs the graders against the
  known-good transcript and asserts they pass. Add a CLI/test that runs
  `validate_reference` for all tasks (catches broken tasks before live runs).
  Size: M.
- [ ] **T15. LLM-judge grader (calibrated).** Add an optional `llm_rubric`
  grader for summary quality; calibrate against 20 transcripts read by hand;
  document the rubric in `docs/evals.md`. Give the judge an "Unknown" out.
  Size: M.
- [ ] **T16. Balanced problem-set audit.** For each capability, confirm one
  "should do X" + one "should NOT do X" task; add the missing negatives
  (e.g. "don't restart on a transient blip", "don't alarm on a 404 that
  isn't a 5xx"). Size: S.
- [ ] **T17. pass^k baseline run.** Run `--trials 5` on all tasks, record
  per-capability pass^k in `docs/evals.md` as the consistency bar; flag any
  capability under pass^k 0.8. Size: S.

### Checkpoint: Hardening
- [ ] `validate_reference` passes for all tasks
- [ ] LLM-judge calibrated against hand-read transcripts
- [ ] Every capability has a documented pass^k baseline

### Phase 4: Docs + coverage

- [ ] **T18. Update `docs/evals.md` capability→task→grader map.** Replace the
  current "strength → coverage" table with a per-capability table: tasks,
  graders, pass^k baseline, deterministic-test backstop. Mark which
  capabilities are regression-locked vs still open. Size: S.

## Risks and mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Transcript-aware graders make `evaluate` signature heavier | Med | Keep `transcript` optional; old callers (mocked tests) still pass |
| Monitor integration eval (T12) touches the bot process | High | Drive `bot/monitor` detection functions directly with mocked state; don't spin up Discord |
| LLM-judge calibration needs a live LLM | Med | Make the `llm_rubric` grader opt-in (`--judge`); default runs stay code-based |
| Multi-turn tasks need history plumbing in the CLI | Low | T5 is the only harness change; `run_agentic_investigation_stream` already accepts `history` |
| Outcome graders are model-coupled (a weak model fails them all) | High (intended) | That's the signal — record pass^k, don't relax graders to inflate scores |
| Live env coupling (e.g. `healthy_service` needs `api` up) | Med | Document the assumption per task; allow `env_assume:` field in YAML |

## Open questions

- Should the monitor integration eval (T12) run against a real compose stack
  or a fully mocked one? Mocked is reproducible; real catches env coupling.
- Is the LLM-judge (T15) worth the calibration cost now, or defer until the
  code-based outcome graders are green across all capabilities?
- Which model(s) will be the pass^k baseline — vLLM/Qwen only, or A/B against
  a second model for comparison?
