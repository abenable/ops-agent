"""Scheduled daily/weekly digests of the watched infrastructure."""

import logging
from datetime import UTC, datetime, time, timedelta

from discord.ext import tasks

from agent.alerting import discord as discord_alert
from agent.bot.monitor import get_monitored_endpoints, in_scope, probe
from agent.bot.summarize import clean
from agent.config.settings import settings
from agent.tools import docker
from agent.watchlist.repository import events_since, list_watched_containers

logger = logging.getLogger(__name__)

_FLAP_THRESHOLD = 2


async def _containers() -> list[dict]:
    """The containers the monitor watches — the same scope rule it alerts on."""
    watched = set(list_watched_containers())
    containers = await docker.list_containers(all_containers=True)
    return [c for c in containers if in_scope(docker.container_name(c), watched)]


async def _snapshot() -> list[str]:
    """Current state of every watched container and endpoint."""
    containers = await _containers()
    lines = [f"**Containers** ({len(containers)})"]
    if containers:
        for c in sorted(containers, key=docker.container_name):
            state = c.get("State", "unknown")
            mark = "" if state == "running" else " ⚠"
            lines.append(f"- `{docker.container_name(c)}` — {state}{mark} ({c.get('Status', '')})")
    else:
        lines.append("- none in scope (is the Docker socket mounted?)")

    endpoints = get_monitored_endpoints()
    lines.append("")
    lines.append(f"**Endpoints** ({len(endpoints)})")
    if endpoints:
        for name, url in sorted(endpoints.items()):
            up = await probe(url)
            lines.append(f"- `{name}` — {'reachable' if up else 'unreachable ⚠'} (<{url}>)")
    else:
        lines.append("- none configured")
    return lines


def _downtime(events: list[dict]) -> dict[str, dict]:
    """Per-target outage counts and total downtime, from paired down/up events."""
    stats: dict[str, dict] = {}
    opened: dict[str, datetime] = {}
    for event in events:
        target = event["target"]
        at = datetime.strptime(event["at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        entry = stats.setdefault(target, {"kind": event["kind"], "outages": 0, "downtime": timedelta()})
        if event["state"] == "down":
            if target not in opened:
                entry["outages"] += 1
                opened[target] = at
        elif target in opened:
            entry["downtime"] += at - opened.pop(target)

    now = datetime.now(UTC)
    for target, since in opened.items():
        stats[target]["downtime"] += now - since
        stats[target]["still_down"] = True
    return stats


def _duration(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"{minutes}m"
    return f"{minutes // 60}h{minutes % 60:02d}m"


def _transitions(events: list[dict]) -> list[str]:
    """Each transition as one line, oldest first."""
    return [
        f"- {e['at'][11:16]} `{e['target']}` {e['state']}"
        for e in events
    ]


async def _with_summary(body: str) -> str:
    summary = await clean(
        body,
        service="today's infrastructure",
        action="write a 2-3 sentence natural-language summary of this report, "
        "highlighting anything noteworthy",
    )
    return f"**Summary**\n{summary}\n\n**Details**\n{body}"


async def build_daily(now: datetime | None = None) -> str:
    """The last 24 hours: current state plus every transition since."""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=1)
    events = events_since(cutoff)
    lines = [*await _snapshot(), "", f"**Since {cutoff:%Y-%m-%d %H:%M} UTC**"]
    lines.extend(_transitions(events) or ["- no changes"])
    return await _with_summary("\n".join(lines))


async def build_weekly(now: datetime | None = None) -> str:
    """The lookback window: current state plus per-target outage totals."""
    now = now or datetime.now(UTC)
    days = settings.digest_lookback_days
    stats = _downtime(events_since(now - timedelta(days=days)))
    lines = [*await _snapshot(), "", f"**Last {days} days**"]
    if stats:
        for target, s in sorted(stats.items()):
            still = ", still down" if s.get("still_down") else ""
            lines.append(
                f"- `{target}` — down {s['outages']}×, total {_duration(s['downtime'])}{still}"
            )
    else:
        lines.append("- no transitions recorded")

    flapping = sorted(t for t, s in stats.items() if s["outages"] >= _FLAP_THRESHOLD)
    if flapping:
        lines.extend(["", "**Why**", await _explain(flapping, days)])
    return await _with_summary("\n".join(lines))


async def _explain(flapping: list[str], days: int) -> str:
    """Let the agent investigate whatever flapped; a template cannot read logs."""
    from agent.workflows import investigate as investigator

    names = ", ".join(f"`{t}`" for t in flapping)
    try:
        return await investigator.investigate(
            f"These targets went down repeatedly in the last {days} days: {names}. "
            "Check their logs and metrics and give one short paragraph on the likely "
            "cause and what an operator should do."
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("weekly narrative failed: %s", exc)
        return f"(could not investigate {names}: {exc})"


async def post(bot, kind: str = "daily", now: datetime | None = None) -> None:
    """Render one digest and post it to the reports channel."""
    channel_id = settings.discord_reports_channel_id
    if not channel_id:
        logger.info("skipping %s digest: DISCORD_REPORTS_CHANNEL_ID is unset", kind)
        return
    now = now or datetime.now(UTC)
    if kind == "weekly":
        body = await build_weekly(now)
        title = f"Weekly report — week ending {now:%Y-%m-%d}"
    else:
        body = await build_daily(now)
        title = f"Daily report — {now:%Y-%m-%d}"
    chunks = [body[i : i + 3900] for i in range(0, len(body), 3900)] or [body]
    logger.info("posting %s digest (%d chars) to channel %s", kind, len(body), channel_id)
    await discord_alert.post_report(channel_id, title, chunks, bot)


async def run_tick(bot, now: datetime | None = None) -> None:
    """One scheduled firing: the daily always, the weekly on its weekday."""
    now = now or datetime.now(UTC)
    await post(bot, "daily", now)
    if now.weekday() == settings.weekly_report_weekday:
        await post(bot, "weekly", now)


def start_digests(bot):
    """Start the once-a-day digest task."""

    @tasks.loop(time=time(hour=settings.report_hour_utc, tzinfo=UTC))
    async def _digest():
        await run_tick(bot)

    _digest.start()


async def post_status(bot, now: datetime | None = None) -> None:
    """Post the current snapshot to the status channel."""
    channel_id = settings.discord_status_channel_id
    if not channel_id:
        logger.info("skipping status update: DISCORD_STATUS_CHANNEL_ID is unset")
        return
    now = now or datetime.now(UTC)
    body = "\n".join(await _snapshot())
    logger.info("posting status update to channel %s", channel_id)
    await discord_alert.send_alert(
        channel_id,
        body,
        bot,
        severity="info",
        title=f"Status \u2014 {now:%Y-%m-%d %H:%M} UTC",
    )


def start_status(bot):
    """Start the periodic status snapshot; the first one fires on startup."""

    @tasks.loop(hours=max(settings.status_interval_hours, 1))
    async def _status():
        await post_status(bot)

    _status.start()
