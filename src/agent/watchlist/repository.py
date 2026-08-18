"""Minimal SQLite repository: the container watch list and the monitor's
transition log (what the daily and weekly digests report on)."""

import sqlite3
from datetime import datetime

from agent.config.settings import DB_PATH
from agent.normalize import resolve_one


def _connect():
    return sqlite3.connect(str(DB_PATH))


# Transitions are rare, but a crash-looping container can log one per poll, so
# the log is trimmed on write rather than growing for the life of the lab.
_EVENT_RETENTION_DAYS = 90


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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                target TEXT NOT NULL,
                kind TEXT NOT NULL,
                state TEXT NOT NULL,
                at TEXT NOT NULL
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
    target = find_watched_container(name)
    if target is None:
        return False
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM watched_containers WHERE name = ?", (target,))
    return cursor.rowcount > 0


def find_watched_container(name: str) -> str | None:
    """Resolve a partial/separator-variant name to an exact watched container name.

    Raises ``AmbiguousName`` when the partial name matches several entries.
    """
    return resolve_one(name, list_watched_containers(), kind="watched containers")


def record_event(target: str, kind: str, state: str) -> None:
    """Log a monitor transition. ``kind`` is 'container' or 'endpoint',
    ``state`` is 'down' or 'up'. Timestamps are SQLite UTC."""
    init_db()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO events (target, kind, state, at) VALUES (?, ?, ?, datetime('now'))",
            (target, kind, state),
        )
        conn.execute(
            "DELETE FROM events WHERE at < datetime('now', ?)",
            (f"-{_EVENT_RETENTION_DAYS} days",),
        )


def events_since(cutoff: datetime) -> list[dict]:
    """Every transition recorded at or after ``cutoff`` (UTC), oldest first."""
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT target, kind, state, at FROM events WHERE at >= ? ORDER BY at",
            (cutoff.strftime("%Y-%m-%d %H:%M:%S"),),
        ).fetchall()
    return [{"target": r[0], "kind": r[1], "state": r[2], "at": r[3]} for r in rows]
