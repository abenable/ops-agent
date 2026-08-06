"""In-memory live agent-activity bus for the web dashboard.

A logging handler captures INFO+ records from the ``agent.*`` loggers and fans
them out to SSE subscribers (the web Activity panel), keeping a small ring
buffer so a freshly connected client sees recent history. Lives only in the
API process, so it mirrors the workflows the web triggers (chat, tasks,
incidents, remediation) rather than the separate bot process.
"""

from __future__ import annotations

import asyncio
import collections
import logging

_BUFFER: collections.deque[dict] = collections.deque(maxlen=200)
_SUBS: set[asyncio.Queue] = set()


class _ActivityHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            evt = {
                "ts": record.created,
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            _BUFFER.append(evt)
            for q in list(_SUBS):
                q.put_nowait(evt)
        except Exception:
            # ponytail: a logging handler must never raise
            pass


def install() -> None:
    """Attach the activity handler to the root ``agent`` logger (idempotent)."""
    root = logging.getLogger("agent")
    if not any(isinstance(h, _ActivityHandler) for h in root.handlers):
        root.addHandler(_ActivityHandler(level=logging.INFO))


def subscribe() -> tuple[list[dict], asyncio.Queue]:
    """Register a new SSE subscriber. Returns (recent history, live queue)."""
    snapshot = list(_BUFFER)
    q: asyncio.Queue = asyncio.Queue()
    _SUBS.add(q)
    return snapshot, q


def unsubscribe(q: asyncio.Queue) -> None:
    _SUBS.discard(q)
