"""Background container monitoring loop for Discord alerts and status updates."""

from datetime import datetime, time, timedelta, timezone

from discord.ext import tasks

from agent.alerting import discord as discord_alert
from agent.config.settings import settings
from agent.memory.repository import list_watched_containers
from agent.helpers import docker
from agent.workflows.reporting import daily_report, weekly_report


# container name -> last state (in-memory; fine for an MVP)
_container_state: dict[str, str] = {}


def _endpoints() -> dict[str, str]:
    out: dict[str, str] = {}
    for pair in settings.monitored_endpoints.split(","):
        if "=" in pair:
            name, url = pair.split("=", 1)
            name = name.strip()
            url = url.strip()
            if name and url:
                out[name] = url
    return out


def get_monitored_endpoints() -> dict[str, str]:
    """Public accessor used by commands and the mention handler."""
    return _endpoints()


async def _poll_containers(bot) -> None:
    """Track containers each cycle and alert when one stops running.

    Alerting is Docker-only — Prometheus is kept for metrics, not alerting — so a
    container stopping is observed straight from the Docker socket: no scrape gap
    and no PromQL edge to mis-fire on a Prometheus restart. A container is in
    scope if it matches ``docker_name_filter`` (empty filter = every container)
    or is explicitly watched via ``/watch``. A running -> not-running transition
    sends a critical alert and opens an incident; not-running -> running sends
    a recovery note to the status channel. The first poll after a monitor
    restart baselines the current state without alerting (``prev`` is None), so
    restarting the monitor never produces a false edge.
    """
    if not settings.docker_monitor:
        return
    watched = set(list_watched_containers())
    try:
        containers = await docker.list_containers(all_containers=True)
    except Exception:
        return

    name_filter = settings.docker_name_filter.lower()
    seen: set[str] = set()
    for c in containers:
        name = docker.container_name(c)
        in_scope = (not name_filter) or (name_filter in name.lower()) or (name in watched)
        if not in_scope:
            continue
        seen.add(name)
        state = c.get("State", "unknown")
        prev = _container_state.get(name)
        if prev == "running" and state != "running" and settings.discord_alert_channel_id:
            await discord_alert.send_alert(
                settings.discord_alert_channel_id,
                f"Container `{name}` is now {state} ({c.get('Status', '')})",
                bot,
                severity="critical",
                title="Container down",
            )
        elif prev is not None and prev != "running" and state == "running" and settings.discord_status_channel_id:
            await discord_alert.send_alert(
                settings.discord_status_channel_id,
                f"Container `{name}` is back running (was {prev})",
                bot,
                severity="info",
                title="Container up",
            )
        _container_state[name] = state

    # Forget containers no longer present or out of scope.
    for name in list(_container_state):
        if name not in seen:
            del _container_state[name]


async def _post_container_snapshot(bot) -> None:
    """Post a compact status snapshot of tracked containers to #status-updates.

    Reuses ``_container_state`` (refreshed every monitor cycle, so at most ~60s
    stale) rather than re-querying Docker. Quiet when no containers are tracked
    or no status channel is configured.
    """
    if not settings.discord_status_channel_id or not _container_state:
        return
    lines = [f"- `{name}`: {state}" for name, state in sorted(_container_state.items())]
    body = "Container status:\n" + "\n".join(lines)
    await discord_alert.send_alert(
        settings.discord_status_channel_id,
        body[:4000],
        bot,
        severity="info",
        title="Container status",
    )


async def _poll_once(bot) -> None:
    """Run one poll iteration (container monitoring; see ``_poll_containers``)."""
    from agent.metrics import MONITOR_CYCLES_TOTAL

    MONITOR_CYCLES_TOTAL.labels(kind="endpoint").inc()
    await _poll_containers(bot)


def _expire_old_logs() -> None:
    """Delete raw ``.log`` files and daily sidecars older than
    ``log_retention_days``. Keeps the human-readable ``.md`` reports."""
    from agent.logstore.collector import LOG_ROOT
    from agent.workflows.reporting import DAILY_DIR

    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=settings.log_retention_days)).isoformat()
    for root in (LOG_ROOT, DAILY_DIR):
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix == ".md":
                continue
            if path.stem < cutoff:
                try:
                    path.unlink()
                except OSError:
                    pass


def start_monitor(bot):
    """Start the periodic endpoint poll and the container-status snapshot loop."""

    @tasks.loop(seconds=max(settings.monitor_interval_seconds, 10))
    async def _poll():
        await _poll_once(bot)

    @tasks.loop(seconds=max(settings.status_snapshot_interval_seconds, 60))
    async def _snapshot():
        await _post_container_snapshot(bot)

    @tasks.loop(seconds=max(settings.log_collect_interval_seconds, 60))
    async def _log_collect():
        from agent.logstore.collector import collect_once

        try:
            await collect_once()
        except Exception:
            pass

    @tasks.loop(time=time(hour=settings.daily_report_hour))
    async def _daily_report():
        if settings.discord_log_channel_id is None:
            return
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
        await discord_alert.send_alert(
            settings.discord_log_channel_id,
            daily_report(yesterday)[:1900],
            bot,
            severity="info",
            title=f"Daily log report {yesterday}",
        )
        # weekly rollup piggybacks on the daily loop the morning of weekly_report_day
        if datetime.now(timezone.utc).weekday() == settings.weekly_report_day:
            await discord_alert.send_alert(
                settings.discord_log_channel_id,
                weekly_report(yesterday)[:1900],
                bot,
                severity="info",
                title=f"Weekly log report {yesterday}",
            )
        _expire_old_logs()

    _poll.start()
    _snapshot.start()
    _log_collect.start()
    _daily_report.start()
