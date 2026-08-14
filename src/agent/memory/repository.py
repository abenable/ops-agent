"""Minimal SQLite repository for incidents and remediation approvals."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from agent.config.settings import settings
from agent.helpers.normalize import normalize

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
            CREATE TABLE IF NOT EXISTS incidents (
                id TEXT PRIMARY KEY,
                service TEXT NOT NULL,
                summary TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                thread_id INTEGER,
                created_at TEXT NOT NULL
            )
            """
        )
        try:
            conn.execute("ALTER TABLE incidents ADD COLUMN thread_id INTEGER")
        except sqlite3.OperationalError:
            pass

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
            CREATE TABLE IF NOT EXISTS pending_approvals (
                id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                container_name TEXT NOT NULL,
                container_id TEXT,
                action TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL
            )
            """
        )


def store_incident(
    service: str,
    summary: str,
    status: str = "open",
    thread_id: int | None = None,
) -> str:
    """Persist an incident and return its short id."""
    init_db()
    incident_id = str(uuid4())[:8]
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO incidents (id, service, summary, status, thread_id, created_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            (incident_id, service, summary, status, thread_id),
        )
    return incident_id


def get_incident(incident_id: str) -> dict | None:
    """Fetch an incident by id."""
    init_db()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, service, summary, status, thread_id, created_at
            FROM incidents
            WHERE id = ?
            """,
            (incident_id,),
        ).fetchone()
    if row is None:
        return None
    return dict(zip(["id", "service", "summary", "status", "thread_id", "created_at"], row))


def update_incident_status(incident_id: str, status: str) -> dict | None:
    """Update an incident status."""
    init_db()
    with _connect() as conn:
        cursor = conn.execute(
            """
            UPDATE incidents
            SET status = ?
            WHERE id = ?
            """,
            (status, incident_id),
        )
        if cursor.rowcount == 0:
            return None
    return get_incident(incident_id)


def update_incident_thread_id(incident_id: str, thread_id: int) -> dict | None:
    """Store the Discord thread id for an incident."""
    init_db()
    with _connect() as conn:
        cursor = conn.execute(
            """
            UPDATE incidents
            SET thread_id = ?
            WHERE id = ?
            """,
            (thread_id, incident_id),
        )
        if cursor.rowcount == 0:
            return None
    return get_incident(incident_id)


def list_incidents(status: str | None = None, limit: int = 50) -> list[dict]:
    """List incidents, optionally filtered by status."""
    init_db()
    query = "SELECT id, service, summary, status, thread_id, created_at FROM incidents"
    params: list = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    columns = ["id", "service", "summary", "status", "thread_id", "created_at"]
    return [dict(zip(columns, row)) for row in rows]


def store_pending_approval(
    incident_id: str,
    container_name: str,
    action: str,
    container_id: str | None = None,
) -> str:
    """Persist a remediation action awaiting human approval and return its short id."""
    init_db()
    approval_id = str(uuid4())[:8]
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO pending_approvals
                (id, incident_id, container_name, container_id, action, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                approval_id,
                incident_id,
                container_name,
                container_id,
                action,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    return approval_id


def get_pending_approval(approval_id: str) -> dict | None:
    """Fetch a pending approval by id."""
    init_db()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, incident_id, container_name, container_id, action, status, created_at
            FROM pending_approvals
            WHERE id = ?
            """,
            (approval_id,),
        ).fetchone()
    if row is None:
        return None
    return dict(
        zip(
            ["id", "incident_id", "container_name", "container_id", "action", "status", "created_at"],
            row,
        )
    )


def set_approval_status(approval_id: str, status: str) -> dict | None:
    """Update an approval's status (e.g. approved / rejected / expired)."""
    init_db()
    with _connect() as conn:
        cursor = conn.execute(
            "UPDATE pending_approvals SET status = ? WHERE id = ?",
            (status, approval_id),
        )
        if cursor.rowcount == 0:
            return None
    return get_pending_approval(approval_id)


def claim_pending_approval(approval_id: str) -> bool:
    """Atomically claim a pending approval for execution (pending -> running).

    Returns True iff this caller won the claim. A conditional UPDATE is the
    check-and-set: under concurrent approvals only one connection transitions
    the row, so the loser sees ``rowcount == 0`` and refuses before touching
    Docker. Guards against double-execution when a button click and ``/approve``
    (or a double-click) race.
    """
    init_db()
    with _connect() as conn:
        cursor = conn.execute(
            "UPDATE pending_approvals SET status = 'running' "
            "WHERE id = ? AND status = 'pending'",
            (approval_id,),
        )
        return cursor.rowcount == 1


def list_pending_approvals(
    incident_id: str | None = None, status: str | None = None, limit: int = 50
) -> list[dict]:
    """List approvals, optionally filtered by incident and/or status."""
    init_db()
    query = (
        "SELECT id, incident_id, container_name, container_id, action, status, created_at "
        "FROM pending_approvals"
    )
    params: list = []
    clauses: list[str] = []
    if incident_id:
        clauses.append("incident_id = ?")
        params.append(incident_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    columns = ["id", "incident_id", "container_name", "container_id", "action", "status", "created_at"]
    return [dict(zip(columns, row)) for row in rows]


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
