"""Command-line entry point: ``agent <command>`` and ``python -m agent``."""

import argparse
import sys

from agent.config.settings import load_env

load_env()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="agent", description="Marconi Infrastructure Operations Agent")
    sub = parser.add_subparsers(dest="command")

    bot = sub.add_parser("bot", help="Run the Discord bot")
    bot.set_defaults(func=_run_bot)

    api = sub.add_parser("api", help="Run the HTTP API")
    api.add_argument("--host", default=None)
    api.add_argument("--port", type=int, default=None)
    api.set_defaults(func=_run_api)

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        sys.exit(1)
    return args.func(args)


def _run_bot(_args):
    from agent.bot.client import run_bot

    run_bot()


def _run_api(args):
    import uvicorn

    from agent.config.settings import settings

    uvicorn.run(
        "agent.api:app",
        host=args.host or settings.api_host,
        port=args.port or settings.api_port,
    )


if __name__ == "__main__":
    main()
