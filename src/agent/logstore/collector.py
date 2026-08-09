"""Cursor-based Docker log collector → plain ``.log`` store.

One ``.log`` file per container per UTC day under ``data/logs/<container>/``.
Each line is ``<iso_ts> <message>`` (what ``docker logs --timestamps`` emits,
after stripping stream-framing control bytes). A per-container cursor in
``data/log_cursors.json`` is written atomically after each flush, so a crash
mid-run resumes from the last saved cursor — no duplicates, no gap.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from agent.config.settings import settings
from agent.storage.repository import list_watched_containers
from agent.tools import docker

LOG_ROOT = Path(settings.database_url.replace("sqlite:///", "")).parent / "logs"
CURSORS_PATH = LOG_ROOT.parent / "log_cursors.json"

_TS_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2}T[\d:.+-]+Z?)\s?(.*)$")

_LEVEL_PREFIX = {
    "error": re.compile(r"^(error|err|fatal|critical|panic)\b", re.I),
    "warn": re.compile(r"^(warn|warning)\b", re.I),
    "info": re.compile(r"^(info|notice)\b", re.I),
    "debug": re.compile(r"^(debug|trace)\b", re.I),
}
_LEVEL_KEYWORD = re.compile(
    r"\b(error|err|fatal|critical|panic|fail|failed|failure|exception|warn|warning)\b",
    re.I,
)
_ERROR_KEYWORDS = {"error", "err", "fatal", "critical", "panic", "fail", "failed", "failure", "exception"}


def _parse_level(message: str) -> str:
    for level, rx in _LEVEL_PREFIX.items():
        if rx.match(message):
            return level
    m = _LEVEL_KEYWORD.search(message)
    if m:
        w = m.group(1).lower()
        return "error" if w in _ERROR_KEYWORDS else "warn"
    return "raw"


def _strip_control(raw: str) -> str:
    """Drop Docker stream-framing bytes and other non-printable control chars."""
    return "".join(c for c in raw if c.isprintable() or c in "\n\t")


def _parse_lines(raw: str, collected_at: str) -> list[tuple[str, str]]:
    """Parse ``docker logs --timestamps`` output into ``(ts, message)`` tuples.

    Lines without a ts prefix keep ``collected_at`` so they're never lost; the
    cursor won't advance for them (worst case a re-fetch on the next cycle).
    """
    out: list[tuple[str, str]] = []
    for line in _strip_control(raw).splitlines():
        if not line.strip():
            continue
        m = _TS_PREFIX.match(line)
        if m:
            out.append((m.group(1), m.group(2)))
        else:
            out.append((collected_at, line))
    return out


def _load_cursors() -> dict[str, str]:
    try:
        return json.loads(CURSORS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_cursors(cursors: dict[str, str]) -> None:
    """Atomic write: tmp file + os.replace so a crash never corrupts state."""
    CURSORS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CURSORS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cursors, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, CURSORS_PATH)


def _append_lines(container: str, parsed: list[tuple[str, str]]) -> str | None:
    """Append ``<ts> <message>`` lines to the per-day ``.log`` file; return the
    last line's ts (or None when nothing was written)."""
    if not parsed:
        return None
    by_day: dict[str, list[str]] = {}
    for ts, message in parsed:
        by_day.setdefault(ts[:10], []).append(f"{ts} {message}")
    last_ts = parsed[-1][0]
    for day, lines in by_day.items():
        path = LOG_ROOT / container / f"{day}.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    return last_ts


async def collect_once() -> dict:
    """Fetch new lines for every watched container and append to the store.

    Returns a per-container line-count summary. No-op per container when
    Docker is unavailable or the container can't be resolved; cursor untouched.
    """
    collected_at = datetime.now(timezone.utc).isoformat()
    cursors = _load_cursors()
    name_filter = settings.docker_name_filter.lower()
    summary: dict[str, int] = {}
    dirty = False

    for name in list_watched_containers():
        if name_filter and name_filter not in name.lower():
            continue
        try:
            target = await docker.find_container(name)
            if target is None:
                continue
            cid = target.get("Id") or docker.container_name(target)
            since = cursors.get(name)
            raw = await docker.container_logs(cid, since=since, timestamps=True)
        except Exception:
            continue

        parsed = _parse_lines(raw, collected_at)
        last_ts = _append_lines(name, parsed)
        if last_ts is not None:
            cursors[name] = last_ts
            dirty = True
        summary[name] = len(parsed)

    if dirty:
        _save_cursors(cursors)
    return summary
