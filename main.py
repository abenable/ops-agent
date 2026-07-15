"""Thin launcher kept for the original entry point.

Prefer running the package directly: `python -m agent`.
"""
from agent.cli import main

if __name__ == "__main__":
    main()
