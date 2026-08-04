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

    ev = sub.add_parser("eval", help="Run automated scenario evaluation")
    ev.add_argument("--scenario", help="Path to a specific scenario YAML (default: all)")
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

    from agent.eval import EvalHarness, discover_scenarios
    from agent.workflows.incident import INCIDENT_SYSTEM_PROMPT, run_agentic_investigation_stream

    async def _run_one(harness: EvalHarness):
        calls: list[str] = []
        summary = ""
        error = None
        try:
            async for event in run_agentic_investigation_stream(
                f"Investigate service {harness.service}.",
                system_prompt=INCIDENT_SYSTEM_PROMPT,
                kind="incident",
            ):
                if event["type"] == "tool_call":
                    calls.append(event["name"])
                elif event["type"] == "done":
                    summary = event.get("content", "")
                elif event["type"] == "error":
                    error = event.get("message", "")
        except Exception as exc:
            error = str(exc)
        return harness.evaluate(tool_calls=calls, summary=summary, error=error)

    if args.scenario:
        harnesses = [EvalHarness(args.scenario)]
    else:
        harnesses = discover_scenarios()
        if not harnesses:
            print("No scenarios found in scenarios/")
            sys.exit(1)

    passed = 0
    failed = 0
    for h in harnesses:
        result = asyncio.run(_run_one(h))
        status = "PASS" if result.passed else "FAIL"
        if result.passed:
            passed += 1
        else:
            failed += 1
        print(
            f"[{status}] {result.scenario:35s} "
            f"score={result.score:.0%} "
            f"({result.matched_actions}/{result.total_actions} actions)"
        )
        if result.error:
            print(f"       error: {result.error}")
        if result.missing_actions:
            print(f"       missing: {', '.join(result.missing_actions)}")
        if result.actual_tool_calls:
            print(f"       calls: {', '.join(result.actual_tool_calls)}")

    print(f"\n{passed} passed, {failed} failed out of {len(harnesses)} scenarios")
    if failed:
        sys.exit(1)
