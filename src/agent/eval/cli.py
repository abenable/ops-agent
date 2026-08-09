"""``agent eval`` CLI subcommand: drive the investigation and grade trials.

The harness (``EvalHarness``) is a pure checker; this module owns the
orchestration — invoke the workflow, collect the transcript + tool calls +
summary, write per-trial JSON and the trials jsonl, and print pass@k / pass^k.

Heavy imports (``agent.workflows``, ``agent.llm``, ``agent.config``) stay lazy
inside :func:`run` so importing :mod:`agent.eval` for the pure-checker / test
path does not pull in the runtime.
"""

from __future__ import annotations


def add_subparser(sub) -> None:
    ev = sub.add_parser("eval", help="Run automated task evaluation")
    ev.add_argument("--task", help="Task name or path (default: all tasks)")
    ev.add_argument(
        "--trials",
        type=int,
        default=1,
        help="Trials per task (default 1). With N>1 computes pass@k / pass^k.",
    )
    ev.add_argument(
        "--label",
        help="Tag this trial (e.g. model name). Default: <provider>:<model>. "
        "Used to group trials across runs in trials.jsonl.",
    )
    ev.add_argument(
        "--out-dir",
        default=None,
        help="Directory to save transcripts and the trial log "
        "(default: src/agent/eval/runs/)",
    )
    ev.add_argument(
        "--judge",
        action="store_true",
        help="Run the opt-in LLM-judge grader for tasks that declare a judge "
        "rubric (Suites 2 and 5). Default: code graders only. The judge never "
        "runs on Suite 3 (safety stays code-only, hard-fail).",
    )
    ev.set_defaults(func=run)


def _default_out_dir() -> "Path":
    # Package-relative runs dir so output never lands in the repo root.
    from pathlib import Path

    return Path(__file__).resolve().parent / "runs"


def _sig(args: dict) -> str:
    """Stable hashable signature for a tool call's args (redundant-call detection)."""
    import json
    return json.dumps(args or {}, sort_keys=True, default=str)


def _path_stats(harness, calls: list[str], transcript: list[dict]) -> dict:
    """Raw path/behaviour signals recorded per trial so ratios (path_ratio,
    redundant_rate, wrong_branch_rate) are pure downstream aggregation.

    - reference_n_tool_calls: len(reference_tool_calls) — the canonical path.
    - tool_call_names: ordered tool names actually called.
    - redundant_calls: tool calls whose (name, args) signature repeats a prior call.
    - off_path_calls: tool calls whose name is not in the reference path
      (the "checked 4 irrelevant services" signal).
    """
    ref = set(harness.reference_tool_calls())
    sigs: list[tuple] = []
    for e in transcript:
        if e.get("type") == "tool_call":
            sigs.append((e.get("name"), _sig(e.get("args") or {})))
    seen: set[str] = set()
    redundant = 0
    for name, s in sigs:
        key = f"{name}|{s}"
        if key in seen:
            redundant += 1
        else:
            seen.add(key)
    off_path = sum(1 for c in calls if c not in ref)
    return {
        "reference_n_tool_calls": len(harness.reference_tool_calls()),
        "tool_call_names": list(calls),
        "redundant_calls": redundant,
        "off_path_calls": off_path,
    }


def _safety_violation(harness, result) -> bool:
    """True only on Suite 3 when the no_mutation grader failed. Kept as its own
    flag so safety is a separate axis, never averaged into an overall score."""
    if harness.suite != "3":
        return False
    return not next((g.passed for g in result.graders if g.name == "no_mutation"), True)


def run(args) -> None:
    import asyncio
    import json
    import time
    from datetime import datetime, timezone
    from pathlib import Path

    from agent.eval.harness import EvalHarness, discover_tasks, aggregate_trials
    from agent.workflows.incident import (
        INCIDENT_SYSTEM_PROMPT,
        run_agentic_investigation_stream,
    )
    from agent.workflows.remediation import run_remediation_workflow
    from agent.llm.client import _resolve
    from agent.config.settings import settings

    provider = settings.llm_provider
    _, model_name = _resolve(provider)
    label = args.label or f"{provider or 'default'}:{model_name}"
    # Filesystem-safe label for the run directory name.
    safe_label = label.replace("/", "_").replace(":", "_").replace(" ", "_")

    out_dir = Path(args.out_dir) if args.out_dir else _default_out_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    trials_jsonl = out_dir / "trials.jsonl"

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = out_dir / f"{ts}_{safe_label}"
    run_dir.mkdir(parents=True, exist_ok=True)

    n_trials = max(1, args.trials)

    async def _run_one_trial(harness: EvalHarness):
        transcript: list[dict] = []
        calls: list[str] = []
        summary = ""
        error: str | None = None
        proposals: list[dict] | None = None
        usage: dict = {}
        t0 = time.monotonic()
        if harness.kind == "remediation":
            try:
                incident_id = f"eval-{ts}"
                res = await run_remediation_workflow(
                    incident_id=incident_id, service=harness.service, diagnosis=harness.diagnosis()
                )
                summary = res.get("summary", "")
                proposals = res.get("proposals", [])
                usage = res.get("usage", {}) or {}
                transcript.append({"type": "remediation", "incident_id": incident_id, "proposals": proposals})
                if proposals:
                    calls.append("propose_restart")
            except Exception as exc:
                error = str(exc)
            duration = time.monotonic() - t0
            result = harness.evaluate(tool_calls=calls, summary=summary, error=error, transcript=transcript, proposals=proposals)
            if args.judge and harness.judge_applicable():
                from agent.eval.graders import llm_judge
                j = await llm_judge(harness, summary=summary, transcript=transcript)
                result.graders.append(j)
                result.passed = result.passed and j.passed
            return result, transcript, duration, usage
        prompt = f"Investigate service {harness.service}."
        if harness.symptom:
            prompt += f" Reported symptom: {harness.symptom}"
        try:
            async for event in run_agentic_investigation_stream(
                prompt,
                system_prompt=INCIDENT_SYSTEM_PROMPT,
                kind="incident",
                history=harness.history() or None,
            ):
                ev = {
                    k: v
                    for k, v in event.items()
                    if k in ("type", "step", "name", "args", "result", "content", "message", "duration_s")
                }
                transcript.append(ev)
                if event["type"] == "tool_call":
                    calls.append(event["name"])
                elif event["type"] == "done":
                    summary = event.get("content", "")
                    usage = event.get("usage", {}) or {}
                elif event["type"] == "error":
                    error = event.get("message", "")
        except Exception as exc:
            error = str(exc)
        duration = time.monotonic() - t0
        result = harness.evaluate(tool_calls=calls, summary=summary, error=error, transcript=transcript)
        if args.judge and harness.judge_applicable():
            from agent.eval.graders import llm_judge
            j = await llm_judge(harness, summary=summary, transcript=transcript)
            result.graders.append(j)
            result.passed = result.passed and j.passed
        return result, transcript, duration, usage

    def _trial_json_obj(h, result, transcript, duration, trial_idx, usage):
        return {
            "timestamp": ts,
            "label": label,
            "model": model_name,
            "provider": provider,
            "trial": trial_idx,
            "task_file": str(h._path),
            "task_name": h.name,
            "task_stem": h.stem,
            "suite": h.suite,
            "kind": h.kind,
            "service": h.service,
            "symptom": h.symptom,
            "expected_actions": h.expected_actions(),
            "expected_evidence": h.expected_evidence(),
            "passed": result.passed,
            "score": result.score,
            "graders": [
                {"name": g.name, "passed": g.passed, "detail": g.detail}
                for g in result.graders
            ],
            "matched_actions": result.matched_actions,
            "total_actions": result.total_actions,
            "missing_actions": result.missing_actions,
            "actual_tool_calls": result.actual_tool_calls,
            "duration_s": round(duration, 3),
            "error": result.error,
            "final_summary": result.final_summary,
            "transcript": transcript,
            "usage": usage,
            **_path_stats(h, result.actual_tool_calls, transcript),
            "safety_violation": _safety_violation(h, result),
        }

    def _trial_row(h, result, duration, trial_idx, transcript_file, usage, calls, transcript):
        # Derived efficiency metrics kept in the row so the plot script can
        # graph them without re-reading every transcript.
        llm_time = float(usage.get("llm_time_s") or 0.0)
        tool_time = float(usage.get("tool_time_s") or 0.0)
        out_tok = int(usage.get("completion_tokens") or 0)
        tot_tok = int(usage.get("total_tokens") or 0)
        ps = _path_stats(h, calls, transcript)
        row = {
            "timestamp": ts,
            "label": label,
            "model": model_name,
            "provider": provider,
            "trial": trial_idx,
            "task": h.stem,
            "suite": h.suite,
            "kind": h.kind,
            "service": h.service,
            "passed": result.passed,
            "score": result.score,
            "graders": {
                g.name: g.passed for g in result.graders
            },
            "matched": result.matched_actions,
            "total": result.total_actions,
            "n_tool_calls": len(result.actual_tool_calls),
            "duration_s": round(duration, 3),
            "error": result.error,
            "summary": result.final_summary,
            "transcript_file": transcript_file,
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": out_tok,
            "total_tokens": tot_tok,
            "cache_read_tokens": int(usage.get("cache_read_tokens") or 0),
            "cache_creation_tokens": int(usage.get("cache_creation_tokens") or 0),
            "n_llm_calls": int(usage.get("n_llm_calls") or 0),
            "n_turns": int(usage.get("n_turns") or 0),
            "llm_time_s": round(llm_time, 3),
            "tool_time_s": round(tool_time, 3),
            "overhead_time_s": round(max(0.0, duration - llm_time - tool_time), 3),
            "time_to_first_token_s": round(float(usage.get("time_to_first_token_s") or 0.0), 3),
            "time_to_last_token_s": round(float(usage.get("time_to_last_token_s") or 0.0), 3),
            "output_tokens_per_sec": round(out_tok / llm_time, 2) if llm_time else 0.0,
            "tokens_per_sec": round(tot_tok / llm_time, 2) if llm_time else 0.0,
            "safety_violation": _safety_violation(h, result),
        }
        row.update(ps)
        return row

    if args.task:
        harnesses = [EvalHarness(args.task)]
    else:
        harnesses = discover_tasks()
        if not harnesses:
            print("No tasks found")
            raise SystemExit(1)

    total_trials = 0
    passed_trials = 0
    per_task_summary = []  # for the final comparison table
    for h in harnesses:
        trial_results: list = []
        for i in range(n_trials):
            result, transcript, duration, usage = asyncio.run(_run_one_trial(h))
            trial_file = run_dir / f"{h.stem}__trial{i}.json"
            trial_file.write_text(
                json.dumps(_trial_json_obj(h, result, transcript, duration, i, usage),
                           default=str),
                encoding="utf-8",
            )
            rel = str(trial_file.relative_to(out_dir))
            with trials_jsonl.open("a", encoding="utf-8") as f:
                f.write(json.dumps(_trial_row(h, result, duration, i, rel, usage,
                                               calls=result.actual_tool_calls, transcript=transcript),
                                   default=str) + "\n")
            trial_results.append(result)
            total_trials += 1
            if result.passed:
                passed_trials += 1
            status = "PASS" if result.passed else "FAIL"
            tok = int(usage.get("total_tokens") or 0)
            print(
                f"[{status}] {result.task:35s} trial {i+1}/{n_trials} "
                f"score={result.score:.0%} "
                f"duration={duration:.1f}s tokens={tok}"
            )
            if result.error:
                print(f"       error: {result.error}")
            bad = [g.name for g in result.graders if not g.passed]
            if bad:
                print(f"       failed graders: {', '.join(bad)}")

        # Per-task summary with pass@k / pass^k.
        agg = aggregate_trials(trial_results)
        summary_file = run_dir / f"{h.stem}__summary.json"
        summary_file.write_text(
            json.dumps(
                {
                    "timestamp": ts,
                    "label": label,
                    "model": model_name,
                    "task": h.stem,
                    "kind": h.kind,
                    "service": h.service,
                    "n_trials": n_trials,
                    **agg,
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        per_task_summary.append((h, agg))

    print(f"\n{passed_trials}/{total_trials} trials passed across {len(harnesses)} tasks")
    if n_trials > 1:
        print(f"\n{'task':28s} {'pass@k':>8s} {'pass^k':>8s} {'score':>6s} {'graders':>s}")
        for h, agg in per_task_summary:
            g = ", ".join(f"{name}={rate:.0%}" for name, rate in agg["graders"].items())
            print(
                f"{h.stem:28s} {agg['pass_at_k']:>8.0%} {agg['pass_k']:>8.0%} "
                f"{agg['score_mean']:>6.0%} {g}"
            )
    print(f"\ntranscripts: {run_dir}/")
    print(f"trials log:  {trials_jsonl}")
    if passed_trials < total_trials:
        raise SystemExit(1)
