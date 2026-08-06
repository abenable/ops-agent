"""Command-line entry points for bot, API, and local workflows."""

import argparse
import sys

from agent.config.dotenv_loader import load_env

load_env()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Marconi Infrastructure Operations Agent")
    sub = parser.add_subparsers(dest="command")

    bot = sub.add_parser("bot", help="Run the Discord bot")
    bot.set_defaults(func=_run_bot)

    api = sub.add_parser("api", help="Run the HTTP API server")
    api.set_defaults(func=_run_api)

    incident = sub.add_parser("incident", help="Run incident workflow for a service")
    incident.add_argument("--service", required=True)
    incident.set_defaults(func=_run_incident)

    report = sub.add_parser("report", help="Generate a report for an incident id")
    report.add_argument("--incident-id", required=True)
    report.set_defaults(func=_run_report)

    ev = sub.add_parser("eval", help="Run automated task evaluation")
    ev.add_argument("--task", help="Path to a specific task YAML (default: all)")
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
        default="eval_runs",
        help="Directory to save transcripts and the trial log (default: eval_runs/)",
    )
    ev.set_defaults(func=_run_eval)

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        sys.exit(1)
    return args.func(args)


def _run_bot(_args):
    from agent.bot.client import run_bot

    run_bot()


def _run_api(_args):
    from agent.api.server import run_api

    run_api()


def _run_incident(args):
    import asyncio

    from agent.workflows.incident import run_incident_workflow

    print(asyncio.run(run_incident_workflow(args.service)))


def _run_report(args):
    from agent.workflows.reporting import run_report_workflow

    print(run_report_workflow(args.incident_id))


def _run_eval(args):
    import asyncio
    import json
    import time
    from datetime import datetime, timezone
    from pathlib import Path

    from agent.eval import EvalHarness, discover_tasks
    from agent.workflows.incident import (
        INCIDENT_SYSTEM_PROMPT,
        run_agentic_investigation_stream,
    )
    from agent.llm.client import _resolve
    from agent.config.settings import settings

    # ponytail: reuse _resolve (in-tree) for the model name; no new public getter.
    provider = settings.llm_provider
    _, model_name = _resolve(provider)
    label = args.label or f"{provider or 'default'}:{model_name}"
    # Filesystem-safe label for the run directory name.
    safe_label = label.replace("/", "_").replace(":", "_").replace(" ", "_")

    out_dir = Path(args.out_dir)
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
        t0 = time.monotonic()
        try:
            async for event in run_agentic_investigation_stream(
                f"Investigate service {harness.service}.",
                system_prompt=INCIDENT_SYSTEM_PROMPT,
                kind="incident",
            ):
                ev = {
                    k: v
                    for k, v in event.items()
                    if k in ("type", "step", "name", "args", "result", "content", "message")
                }
                transcript.append(ev)
                if event["type"] == "tool_call":
                    calls.append(event["name"])
                elif event["type"] == "done":
                    summary = event.get("content", "")
                elif event["type"] == "error":
                    error = event.get("message", "")
        except Exception as exc:
            error = str(exc)
        duration = time.monotonic() - t0
        result = harness.evaluate(tool_calls=calls, summary=summary, error=error)
        return result, transcript, duration

    def _trial_json_obj(h, result, transcript, duration, trial_idx):
        return {
            "timestamp": ts,
            "label": label,
            "model": model_name,
            "provider": provider,
            "trial": trial_idx,
            "task_file": str(h._path),
            "task_name": h.name,
            "task_stem": h.stem,
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
        }

    def _trial_row(h, result, duration, trial_idx, transcript_file):
        return {
            "timestamp": ts,
            "label": label,
            "model": model_name,
            "provider": provider,
            "trial": trial_idx,
            "task": h.stem,
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
        }

    if args.task:
        harnesses = [EvalHarness(args.task)]
    else:
        harnesses = discover_tasks()
        if not harnesses:
            print("No tasks found in tasks/")
            sys.exit(1)

    from agent.eval import aggregate_trials

    total_trials = 0
    passed_trials = 0
    per_task_summary = []  # for the final comparison table
    for h in harnesses:
        trial_results: list = []
        for i in range(n_trials):
            result, transcript, duration = asyncio.run(_run_one_trial(h))
            trial_file = run_dir / f"{h.stem}__trial{i}.json"
            trial_file.write_text(
                json.dumps(_trial_json_obj(h, result, transcript, duration, i),
                           indent=2, default=str),
                encoding="utf-8",
            )
            rel = str(trial_file.relative_to(out_dir))
            with trials_jsonl.open("a", encoding="utf-8") as f:
                f.write(json.dumps(_trial_row(h, result, duration, i, rel),
                                   default=str) + "\n")
            trial_results.append(result)
            total_trials += 1
            if result.passed:
                passed_trials += 1
            status = "PASS" if result.passed else "FAIL"
            print(
                f"[{status}] {result.task:35s} trial {i+1}/{n_trials} "
                f"score={result.score:.0%} "
                f"duration={duration:.1f}s"
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
        sys.exit(1)
