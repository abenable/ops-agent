"""Read the plain ``.log`` store back, filtered by container and time range.

Each ``<iso_ts> <message>`` line is parsed into ``{ts, level, raw}`` at read
time. Streams line-by-line so a huge day file never loads fully into memory.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agent.logstore import collector

_TS_PREFIX = collector._TS_PREFIX
_parse_level = collector._parse_level


def _parse_record(line: str) -> dict | None:
    """Parse one ``<iso_ts> <message>`` line into ``{ts, level, raw}``; None
    for a line without a timestamp prefix."""
    m = _TS_PREFIX.match(line)
    if not m:
        return None
    ts, message = m.group(1), m.group(2)
    return {"ts": ts, "level": _parse_level(message), "raw": message}


def _days_between(start: datetime, end: datetime) -> list[str]:
    """Inclusive list of ``YYYY-MM-DD`` UTC day strings from start..end."""
    days: list[str] = []
    cur = start.astimezone(timezone.utc).date()
    last = end.astimezone(timezone.utc).date()
    while cur <= last:
        days.append(cur.isoformat())
        cur += timedelta(days=1)
    return days


def _iter_file(path, since: datetime | None, until: datetime | None):
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            rec = _parse_record(line)
            if rec is None:
                continue
            if since is not None or until is not None:
                try:
                    ts = datetime.fromisoformat(rec["ts"].replace("Z", "+00:00"))
                except ValueError:
                    ts = None
                if ts is not None:
                    if since is not None and ts < since:
                        continue
                    if until is not None and ts > until:
                        continue
            yield rec


def iter_lines(
    container: str,
    since: datetime | None = None,
    until: datetime | None = None,
):
    """Yield stored records for *container* within [since, until]; no bounds
    yields everything on disk, days in order, chronological within a day."""
    root = collector.LOG_ROOT / container
    if not root.exists():
        return
    if since is None and until is None:
        days = sorted(p.stem for p in root.glob("*.log"))
    elif since is not None and until is None:
        start = since.astimezone(timezone.utc).date().isoformat()
        days = sorted(p.stem for p in root.glob("*.log") if p.stem >= start)
    elif since is None and until is not None:
        end = until.astimezone(timezone.utc).date().isoformat()
        days = sorted(p.stem for p in root.glob("*.log") if p.stem <= end)
    else:
        days = [d for d in _days_between(since, until) if (root / f"{d}.log").exists()]
    for day in days:
        yield from _iter_file(root / f"{day}.log", since, until)


def iter_lines_for_day(container: str, day: str):
    """Yield every record for *container* on the given ``YYYY-MM-DD`` (UTC)."""
    path = collector.LOG_ROOT / container / f"{day}.log"
    if path.exists():
        yield from _iter_file(path, None, None)


def line_count(container: str, day: str) -> int:
    """Cheap count of records for *container* on *day* (line count, not parse)."""
    path = collector.LOG_ROOT / container / f"{day}.log"
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as fh:
        return sum(1 for line in fh if line.strip())
