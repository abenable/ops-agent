"""Incident + log reporting workflows.

``daily_report`` / ``weekly_report`` aggregate the ``.log`` store into
markdown for Discord and persist a JSON sidecar so the weekly rollup reads the
daily summaries — not the raw logs again.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from agent.config.settings import settings
from agent.logstore.reader import iter_lines, iter_lines_for_day
from agent.memory.repository import get_incident, list_watched_containers

REPORT_ROOT = Path(settings.database_url.replace("sqlite:///", "")).parent / "reports"
DAILY_DIR = REPORT_ROOT / "daily"

_ERROR_LEVELS = {"error", "fatal", "critical", "panic"}
_WARN_LEVELS = {"warn", "warning"}

# `raw` keeps the level prefix (useful for the agent's display); strip it here
# so the same error repeated with different prefixes groups to one message.
_NORM_LEVEL = re.compile(r"^(error|err|fatal|critical|panic|warn|warning|info|notice|debug|trace)\b[\s:\-]*", re.I)
_NORM_TS = re.compile(r"\b\d{4}-\d{2}-\d{2}T[\d:.+\-Z]+\b")
_NORM_HEX = re.compile(r"\b[0-9a-fA-F]{8,}\b")
_NORM_NUM = re.compile(r"\b\d+\b")
_NORM_BRACKET = re.compile(r"^\[[^\]]*\]\s*")
_NORM_GUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")


def _normalize_message(msg: str) -> str:
    msg = _NORM_LEVEL.sub("", msg, count=1)
    msg = _NORM_BRACKET.sub("", msg)
    msg = _NORM_GUID.sub("<guid>", msg)
    msg = _NORM_HEX.sub("<hex>", msg)
    msg = _NORM_TS.sub("<ts>", msg)
    msg = _NORM_NUM.sub("<n>", msg)
    return msg.strip()


def run_report_workflow(incident_id: str) -> str:
    """Retrieve a stored incident and return a formatted report."""
    incident = get_incident(incident_id)
    if incident is None:
        return f"No incident found with id {incident_id}"
    return (
        f"Incident {incident['id']} ({incident['service']})\n"
        f"Created at: {incident['created_at']}\n"
        f"Summary: {incident['summary']}"
    )


def _container_day_summary(container: str, day: str) -> dict:
    lines = list(iter_lines_for_day(container, day))
    errors = [r for r in lines if r.get("level") in _ERROR_LEVELS]
    warns = [r for r in lines if r.get("level") in _WARN_LEVELS]
    grouped = Counter(_normalize_message(r.get("raw", "")) for r in errors)
    return {
        "container": container,
        "lines": len(lines),
        "errors": len(errors),
        "warnings": len(warns),
        "top_errors": grouped.most_common(5),
    }


def daily_report(day: str | None = None) -> str:
    """Build a markdown daily log report for *day* (``YYYY-MM-DD``, UTC; default
    yesterday), persist it + a JSON sidecar, and return the markdown for Discord.
    """
    d = date.fromisoformat(day) if day else (datetime.now(timezone.utc).date() - timedelta(days=1))
    iso = d.isoformat()
    prev = (d - timedelta(days=1)).isoformat()

    summaries = []
    today_err_groups: Counter = Counter()
    prev_err_groups: Counter = Counter()
    for name in list_watched_containers():
        s = _container_day_summary(name, iso)
        if s["lines"]:
            summaries.append(s)
        today_err_groups.update({k: 1 for k, _ in s["top_errors"]})
        prev_err_groups.update(
            {_normalize_message(r.get("raw", "")): 1 for r in iter_lines_for_day(name, prev)
             if r.get("level") in _ERROR_LEVELS}
        )

    first_seen = sorted(g for g in today_err_groups if g and g not in prev_err_groups)

    md = [f"# Daily log report — {iso}", ""]
    if not summaries:
        md.append("_No log lines collected for any watched container._")
    else:
        md.append("| Container | Lines | Errors | Warnings |")
        md.append("|---|---:|---:|---:|")
        for s in summaries:
            md.append(f"| `{s['container']}` | {s['lines']} | {s['errors']} | {s['warnings']} |")
        md.append("")
        any_errors = False
        for s in summaries:
            if not s["top_errors"]:
                continue
            any_errors = True
            md.append(f"### `{s['container']}` — top errors")
            for msg, n in s["top_errors"]:
                md.append(f"- ({n}×) `{msg[:200]}`")
            md.append("")
        if not any_errors:
            md.append("_No error-level lines recorded._")
        md.append("### First-seen today")
        if first_seen:
            for msg in first_seen[:10]:
                md.append(f"- `{msg[:200]}`")
        else:
            md.append("_None._")

    body = "\n".join(md)
    _persist_daily(iso, body, summaries, first_seen)
    return body


def _persist_daily(iso: str, body: str, summaries: list[dict], first_seen: list[str]) -> None:
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    (DAILY_DIR / f"{iso}.md").write_text(body, encoding="utf-8")
    payload = {"day": iso, "containers": summaries, "first_seen": first_seen}
    (DAILY_DIR / f"{iso}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_daily_json(iso: str) -> dict | None:
    path = DAILY_DIR / f"{iso}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def weekly_report(end_day: str | None = None) -> str:
    """Aggregate the 7 daily sidecars ending at *end_day* (default today)."""
    end = date.fromisoformat(end_day) if end_day else datetime.now(timezone.utc).date()
    days = [(end - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    dailies = [d for d in (_load_daily_json(x) for x in days) if d]

    if not dailies:
        return f"# Weekly log report — Week ending {end.isoformat()}\n\n_No daily reports available._"

    per_container: dict[str, list[int]] = {}
    first_seen_week: list[str] = []
    for d in dailies:
        for s in d.get("containers", []):
            per_container.setdefault(s["container"], [0] * 7)
            idx = days.index(d["day"])
            per_container[s["container"]][idx] = s["errors"]
        first_seen_week.extend(d.get("first_seen", []))

    # repeat offenders: appeared on >=4 of the 7 days
    offender_days: dict[str, int] = {}
    for d in dailies:
        seen_this_day = set()
        for s in d.get("containers", []):
            for msg, _ in s.get("top_errors", []):
                seen_this_day.add(msg)
        for msg in seen_this_day:
            offender_days[msg] = offender_days.get(msg, 0) + 1
    repeat_offenders = sorted((m for m, n in offender_days.items() if n >= 4), key=lambda m: -offender_days[m])

    md = [f"# Weekly log report — Week ending {end.isoformat()}", ""]
    md.append("### Error counts per day (per container)")
    md.append("| Container | " + " | ".join(days) + " |")
    md.append("|---" + "|---:" * 7 + "|")
    for name, counts in sorted(per_container.items()):
        md.append(f"| `{name}` | " + " | ".join(str(c) for c in counts) + " |")
    md.append("")
    md.append("### Repeat offenders (≥4 of 7 days)")
    if repeat_offenders:
        for msg in repeat_offenders[:15]:
            md.append(f"- `{msg[:200]}`")
    else:
        md.append("_None._")
    md.append("")
    md.append("### New issues first seen this week")
    if first_seen_week:
        for msg in list(dict.fromkeys(first_seen_week))[:15]:
            md.append(f"- `{msg[:200]}`")
    else:
        md.append("_None._")
    return "\n".join(md)
