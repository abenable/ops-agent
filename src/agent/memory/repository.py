"""Minimal SQLite repository for the container watch list."""

import sqlite3
from pathlib import Path

from agent.config.settings import settings
from agent.normalize import normalize

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DB_PATH = Path(settings.database_url.replace("sqlite:///", ""))
if not _DB_PATH.is_absolute():
    _DB_PATH = _REPO_ROOT / _DB_PATH
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def _connect():
    return sqlite3.connect(str(_DB_PATH))


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS watched_containers (
                name TEXT PRIMARY KEY,
                created_at TEXT NOT NULL
            )
            """
        )


def list_watched_containers() -> list[str]:
    """Return the names of containers the operator chose to watch."""
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT name FROM watched_containers ORDER BY name COLLATE NOCASE"
        ).fetchall()
    return [row[0] for row in rows]


def add_watched_container(name: str) -> bool:
    """Persist a watched container. Returns True when newly added, False if already present."""
    init_db()
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO watched_containers (name, created_at) VALUES (?, datetime('now'))",
            (name,),
        )
    return cursor.rowcount > 0


def remove_watched_container(name: str) -> bool:
    """Remove a watched container (separator-agnostic). Returns True if one was removed."""
    init_db()
    watched = list_watched_containers()
    target = find_watched_container(name) if name not in watched else name
    if target is None:
        return False
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM watched_containers WHERE name = ?", (target,))
    return cursor.rowcount > 0


def is_watched(name: str) -> bool:
    """Check whether a container name is in the watch list."""
    return name in list_watched_containers()


def find_watched_container(name: str) -> str | None:
    """Resolve a partial/separator-variant name to an exact watched container name."""
    needle = normalize(name)
    for candidate in list_watched_containers():
        if needle in normalize(candidate):
            return candidate
    return None
