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
