# Eval-build todo

## Phase 1: Grader infrastructure (foundation)
- [ ] T1. Pass `transcript` to `EvalHarness.evaluate`; outcome-grader base
- [ ] T2. Upgrade `groundedness` to check `tool_result` events (not just summary)
- [ ] T3. Add `no_hallucination` grader (summary names only containers from `list_services`)
- [ ] T4. Add `right_source` grader for `kind: logs` tasks
- [ ] T5. Multi-turn task support (`history:` field → `run_agentic_investigation_stream`)

### Checkpoint: Foundation
- [ ] `uv run pytest tests/test_eval.py` green
- [ ] `python -m agent eval --task tasks/loki_no_logs.yml` still passes
- [ ] No regression in the 7 existing tasks

## Phase 2: Capability eval suites (vertical slices)
- [ ] T6. "Read the right logs" suite (logs_loki_hit, logs_loki_miss) + `right_source`
- [ ] T7. "Tell container status" suite (status_running, status_stopped_misnamed, status_healthy_no_alarm) + `no_hallucination`
- [ ] T8. "Report performance" suite (perf_latency, perf_request_rate) + metric-family grader
- [ ] T9. Upgrade "find root cause" suite to outcome grading + cascading-failure stretch task
- [ ] T10. "Conversational memory" task (memory_resolve_that_container) — depends on T5
- [ ] T11. "@mention grounding" task (grounding_no_hallucination)
- [ ] T12. "Identify incidents" integration eval (down → incident → investigation graded)
- [ ] T13. "Remediation proposal" eval (right restart, right container, exactly one)

### Checkpoint: Capability suites
- [ ] Every capability has ≥1 positive + ≥1 negative task
- [ ] `python -m agent eval` runs all; trials.jsonl records per-grader rates
- [ ] `uv run pytest -q` green

## Phase 3: Article-aligned hardening
- [ ] T14. Reference solutions (`reference_summary`, `reference_tool_calls`) + `EvalHarness.validate_reference()` for all tasks
- [ ] T15. LLM-judge grader, calibrated against 20 hand-read transcripts
- [ ] T16. Balanced problem-set audit (should / should-NOT per capability)
- [ ] T17. pass^k baseline run (`--trials 5`) → `docs/evals.md` consistency bar

### Checkpoint: Hardening
- [ ] `validate_reference` passes for all tasks
- [ ] LLM-judge calibrated
- [ ] Every capability has a pass^k baseline

## Phase 4: Docs
- [ ] T18. Update `docs/evals.md` capability→task→grader map + regression-locked vs open

## Notes
- Deterministic-only capabilities (edge-trigger dedup, atomic approval claim,
  `normalize`, watch-list persistence) stay in `tests/test_*.py`; the eval
  harness covers the LLM-driven surface of each capability.
- Grade outcomes, not paths. Don't relax graders to inflate scores — a low
  pass^k on a capability is the signal, not a bug to fix in the grader.
