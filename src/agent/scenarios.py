"""Scenario discovery and safe path resolution, shared by the bot and the API.

Kept free of discord imports so the FastAPI server can list and run scenarios
without pulling the discord.py stack.
"""

from __future__ import annotations

from pathlib import Path

import yaml

SCENARIOS_DIR = Path("scenarios")


def scenario_path(name: str) -> Path | None:
    """Resolve a scenario name to its file under ``scenarios/``, rejecting path
    traversal. Returns the path if it is a safe name with a ``.yml`` file, else
    None. Guards ``!scenario`` / ``/scenario`` / the API runner against
    ``../../etc/passwd``-style reads of arbitrary files outside scenarios/."""
    if not name or "/" in name or "\\" in name:
        return None
    base = SCENARIOS_DIR.resolve()
    path = base / f"{name}.yml"
    try:
        path.relative_to(base)
    except ValueError:
        return None
    return path if path.exists() else None


def available_scenarios() -> list[str]:
    """Return scenario names (file stems) under ``scenarios/``, sorted."""
    if not SCENARIOS_DIR.is_dir():
        return []
    return sorted(p.stem for p in SCENARIOS_DIR.glob("*.yml"))


def load_scenario(name: str) -> dict | None:
    """Parse ``scenarios/<name>.yml`` with ``yaml.safe_load`` or return None if
    the name is unsafe or the file is missing."""
    path = scenario_path(name)
    if path is None:
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))
