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

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        sys.exit(1)
    return args.func(args)


def _run_bot(_args):
    from agent.bot.client import run_bot

    run_bot()


if __name__ == "__main__":
    main()
