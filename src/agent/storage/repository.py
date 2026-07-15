"""Minimal SQLite repository for incidents."""

import sqlite3
from pathlib import Path
from uuid import uuid4

from agent.config.settings import settings

_DB_PATH = Path(settings.database_url.replace("sqlite:///", ""))
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
                created_at TEXT NOT NULL
            )
            """
        )
        # ponytail: lightweight migration for existing MVP databases
        try:
            conn.execute("ALTER TABLE incidents ADD COLUMN status TEXT NOT NULL DEFAULT 'open'")
        except sqlite3.OperationalError:
            pass


def store_incident(service: str, summary: str, status: str = "open") -> str:
    """Persist an incident and return its short id."""
    init_db()
    incident_id = str(uuid4())[:8]
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO incidents (id, service, summary, status, created_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            """,
            (incident_id, service, summary, status),
        )
    return incident_id


def get_incident(incident_id: str) -> dict | None:
    """Fetch an incident by id."""
    init_db()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, service, summary, status, created_at
            FROM incidents
            WHERE id = ?
            """,
            (incident_id,),
        ).fetchone()
    if row is None:
        return None
    return dict(zip(["id", "service", "summary", "status", "created_at"], row))


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


def list_incidents(status: str | None = None, limit: int = 50) -> list[dict]:
    """List incidents, optionally filtered by status."""
    init_db()
    query = "SELECT id, service, summary, status, created_at FROM incidents"
    params: list = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    columns = ["id", "service", "summary", "status", "created_at"]
    return [dict(zip(columns, row)) for row in rows]
