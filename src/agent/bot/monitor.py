"""Background monitoring loop: polls containers and HTTP endpoints, and posts
Discord alerts on down/recovery transitions."""

import httpx2 as httpx
from discord.ext import tasks

from agent.alerting import discord as discord_alert
from agent.config.settings import settings
from agent.tools import docker
from agent.watchlist.repository import list_watched_containers

# container name -> last state (in-memory; fine for an MVP)
_container_state: dict[str, str] = {}
# endpoint name -> last reachability (in-memory, same lifetime as above)
_endpoint_state: dict[str, bool] = {}


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

    Container alerting reads the Docker socket directly rather than PromQL —
    Prometheus is kept for metrics, not alerting — so there is no scrape gap and
    no PromQL edge to mis-fire on a Prometheus restart. A container is in
    scope if it matches ``docker_name_filter`` (empty filter = every container)
    or is explicitly watched via ``/watch``. A running -> not-running transition
    sends a critical alert; not-running -> running sends a recovery note to
    the status channel. The first poll after a monitor
    restart baselines the current state without alerting (``prev`` is None), so
    restarting the monitor never produces a false edge.
    """
    if not settings.docker_monitor:
        return
    watched = set(list_watched_containers())
    try:
        containers = await docker.list_containers(all_containers=True)
    except Exception:  # noqa: BLE001 - one bad poll must not kill the monitor loop
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


async def _probe(url: str) -> bool:
    """True when the endpoint answers with a non-error status."""
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(url)
        return response.status_code < 400
    except (httpx.HTTPError, OSError):
        return False


async def _poll_endpoints(bot) -> None:
    """Probe each configured endpoint and alert on down/recovery transitions.

    Covers the systems that are not containers on this host (a URL on another
    box, a service behind a proxy), which the Docker poll cannot see. Like the
    container poll, the first observation of an endpoint only baselines it
    (``prev`` is None), so a restart never produces a false alarm.
    """
    endpoints = _endpoints()
    for name, url in endpoints.items():
        up = await _probe(url)
        prev = _endpoint_state.get(name)
        _endpoint_state[name] = up
        if prev is None or prev == up:
            continue
        if not up and settings.discord_alert_channel_id:
            await discord_alert.send_alert(
                settings.discord_alert_channel_id,
                f"Endpoint `{name}` is unreachable (<{url}>)",
                bot,
                severity="critical",
                title="Endpoint down",
            )
        elif up and settings.discord_status_channel_id:
            await discord_alert.send_alert(
                settings.discord_status_channel_id,
                f"Endpoint `{name}` is reachable again (<{url}>)",
                bot,
                severity="info",
                title="Endpoint up",
            )

    # Forget endpoints removed from the configuration.
    for name in list(_endpoint_state):
        if name not in endpoints:
            del _endpoint_state[name]


def start_monitor(bot):
    """Start the periodic poll that drives container and endpoint alerts."""

    @tasks.loop(seconds=max(settings.monitor_interval_seconds, 10))
    async def _poll():
        await _poll_containers(bot)
        await _poll_endpoints(bot)

    _poll.start()
