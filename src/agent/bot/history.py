"""Small per-channel conversation history so Oracle remembers the current topic."""

import sqlite3
import textwrap

from agent.storage import repository as _repo

_HISTORY_LIMIT = 10  # keep prompt size small


def _connect():
    # piggy-back on the repository's db path so tests only need to patch one place
    return sqlite3.connect(str(_repo._DB_PATH))


def init_history_db() -> None:
    """Create the history table if it does not exist."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_conversation_history_channel
            ON conversation_history (channel_id, created_at)
            """
        )


def add_message(channel_id: int, role: str, content: str) -> None:
    """Store one side of a conversation turn and cap the retained history."""
    init_history_db()
    # Avoid storing huge tool outputs; history is for context, not log shipping.
    trimmed = textwrap.shorten(content, width=4000, placeholder="…")
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO conversation_history (channel_id, role, content)
            VALUES (?, ?, ?)
            """,
            (channel_id, role, trimmed),
        )
        # Cap at 20 stored rows per channel, which is more than we include in prompts.
        conn.execute(
            """
            DELETE FROM conversation_history
            WHERE channel_id = ?
              AND id NOT IN (
                  SELECT id FROM conversation_history
                  WHERE channel_id = ?
                  ORDER BY created_at DESC LIMIT 20
              )
            """,
            (channel_id, channel_id),
        )


def get_history(channel_id: int, limit: int = _HISTORY_LIMIT) -> list[dict]:
    """Return the most recent conversation turns for a channel."""
    init_history_db()
    query = """
        SELECT role, content
        FROM conversation_history
        WHERE channel_id = ?
        ORDER BY created_at DESC
        LIMIT ?
    """
    with _connect() as conn:
        rows = conn.execute(query, (channel_id, limit)).fetchall()
    rows.reverse()
    return [dict(zip(["role", "content"], row)) for row in rows]


def format_history(channel_id: int, limit: int = _HISTORY_LIMIT) -> str:
    """Render the stored history as a short block the prompt can include."""
    turns = get_history(channel_id, limit)
    if not turns:
        return ""
    lines = []
    for turn in turns:
        who = "User" if turn["role"] == "user" else "Oracle"
        lines.append(f"{who}: {turn['content']}")
    return "\n".join(lines)
