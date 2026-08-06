"""Task discovery and safe path resolution, shared by the eval system, the bot,
and the API.

A *task* is a YAML file under ``tasks/`` that describes a simulated
infrastructure failure: a service, a symptom, and the agent actions the eval
expects. The operator-facing Discord command ``/task`` and the
``/api/tasks`` endpoint load these same files and present them to operators
as "tasks" — the on-disk unit is a task, the operator verb is a task.

Kept free of discord imports so the FastAPI server can list and run tasks
without pulling the discord.py stack.
"""

from __future__ import annotations

from pathlib import Path

import yaml

TASKS_DIR = Path("tasks")


def task_path(name: str) -> Path | None:
    """Resolve a task name to its file under ``tasks/``, rejecting path
    traversal. Returns the path if it is a safe name with a ``.yml`` file, else
    None. Guards ``/task`` / the API runner against
    ``../../etc/passwd``-style reads of arbitrary files outside tasks/."""
    if not name or "/" in name or "\\" in name:
        return None
    base = TASKS_DIR.resolve()
    path = base / f"{name}.yml"
    try:
        path.relative_to(base)
    except ValueError:
        return None
    return path if path.exists() else None


def available_tasks() -> list[str]:
    """Return task names (file stems) under ``tasks/``, sorted."""
    if not TASKS_DIR.is_dir():
        return []
    return sorted(p.stem for p in TASKS_DIR.glob("*.yml"))


def load_task(name: str) -> dict | None:
    """Parse ``tasks/<name>.yml`` with ``yaml.safe_load`` or return None if
    the name is unsafe or the file is missing."""
    path = task_path(name)
    if path is None:
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))
