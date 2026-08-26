"""Background monitoring loop: polls containers and HTTP endpoints, and posts Discord alerts on down/recovery transitions."""

import asyncio
import logging

import httpx2 as httpx
from discord.ext import tasks

from agent.alerting import discord as discord_alert
from agent.config.settings import settings
from agent.tools import docker, prometheus
from agent.watchlist.repository import list_watched_containers, record_event

logger = logging.getLogger(__name__)

_container_state: dict[str, str] = {}
_endpoint_state: dict[str, bool] = {}
_rule_state: dict[str, bool] = {}
# ponytail: strong refs so the loop's own tasks are not garbage collected mid-run
_incident_tasks: set[asyncio.Task] = set()


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


def _alert_rules() -> dict[str, str]:
    """Parse ``PROMETHEUS_ALERT_RULES`` into ``name -> promql``.

    Split on the first ``=`` only: a PromQL expression frequently contains one
    (``up == 0``), so anything stricter would silently drop the useful rules.
    """
    out: dict[str, str] = {}
    for pair in settings.prometheus_alert_rules.split(","):
        if "=" not in pair:
            continue
        name, expr = pair.split("=", 1)
        name, expr = name.strip(), expr.strip()
        if name and expr:
            out[name] = expr
    return out


def get_alert_rules() -> dict[str, str]:
    """Public accessor for the configured PromQL alert rules."""
    return _alert_rules()


def get_monitored_endpoints() -> dict[str, str]:
    """Public accessor used by commands and the mention handler."""
    return _endpoints()


def in_scope(name: str, watched: set[str]) -> bool:
    """True when a container is alerted on: matches ``docker_name_filter`` or is explicitly watched."""
    name_filter = settings.docker_name_filter.lower()
    return (not name_filter) or (name_filter in name.lower()) or (name in watched)


async def _poll_containers(bot) -> None:
    """Track containers each cycle and alert when one stops running."""
    if not settings.docker_monitor:
        return
    watched = set(list_watched_containers())
    try:
        containers = await docker.list_containers(all_containers=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("container poll failed: %s", exc)
        return

    seen: set[str] = set()
    for c in containers:
        name = docker.container_name(c)
        if not in_scope(name, watched):
            continue
        seen.add(name)
        state = c.get("State", "unknown")
        prev = _container_state.get(name)
        if prev == "running" and state != "running":
            logger.info("container %s: running -> %s", name, state)
            record_event(name, "container", "down")
            if settings.discord_alert_channel_id:
                await discord_alert.send_alert(
                    settings.discord_alert_channel_id,
                    f"Container `{name}` is now {state} ({c.get('Status', '')})",
                    bot,
                    severity="critical",
                    title="Container down",
                )
        elif prev is not None and prev != "running" and state == "running":
            logger.info("container %s: %s -> running", name, prev)
            record_event(name, "container", "up")
            if settings.discord_status_channel_id:
                await discord_alert.send_alert(
                    settings.discord_status_channel_id,
                    f"Container `{name}` is back running (was {prev})",
                    bot,
                    severity="info",
                    title="Container up",
                )
        _container_state[name] = state

    for name in list(_container_state):
        if name not in seen:
            del _container_state[name]


async def probe(url: str) -> bool:
    """True when the endpoint answers with a non-error status."""
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(url)
        return response.status_code < 400
    except (httpx.HTTPError, OSError):
        return False


async def _poll_endpoints(bot) -> None:
    """Probe each configured endpoint and alert on down/recovery transitions."""
    endpoints = _endpoints()
    for name, url in endpoints.items():
        up = await probe(url)
        prev = _endpoint_state.get(name)
        _endpoint_state[name] = up
        if prev is None or prev == up:
            continue
        logger.info("endpoint %s: %s", name, "up" if up else "down")
        record_event(name, "endpoint", "up" if up else "down")
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

    for name in list(_endpoint_state):
        if name not in endpoints:
            del _endpoint_state[name]


async def _rule_firing(promql: str) -> bool | None:
    """True when the query returns any series; None when it could not be run."""
    try:
        payload = await prometheus.query(promql)
    except Exception as exc:  # noqa: BLE001
        logger.warning("alert rule query failed: %s", exc)
        return None
    if payload.get("status") != "success":
        logger.warning("alert rule query rejected: %s", payload.get("error", payload.get("status")))
        return None
    return bool((payload.get("data") or {}).get("result"))


async def _poll_alert_rules(bot) -> None:
    """Evaluate each PromQL rule and alert on the transition into firing."""
    if not settings.prometheus_url:
        return
    rules = _alert_rules()
    for name, promql in rules.items():
        firing = await _rule_firing(promql)
        if firing is None:
            continue
        prev = _rule_state.get(name)
        _rule_state[name] = firing
        if prev is None or prev == firing:
            continue
        logger.info("alert rule %s: %s", name, "firing" if firing else "resolved")
        record_event(name, "rule", "down" if firing else "up")
        if firing and settings.discord_alert_channel_id:
            await discord_alert.send_alert(
                settings.discord_alert_channel_id,
                f"PromQL rule `{name}` is firing:\n```\n{promql}\n```",
                bot,
                severity="critical",
                title="Alert rule firing",
            )
            _spawn_incident(bot, name, promql)
        elif not firing and settings.discord_status_channel_id:
            await discord_alert.send_alert(
                settings.discord_status_channel_id,
                f"PromQL rule `{name}` has resolved",
                bot,
                severity="info",
                title="Alert rule resolved",
            )

    for name in list(_rule_state):
        if name not in rules:
            del _rule_state[name]


def _spawn_incident(bot, name: str, promql: str) -> None:
    """Run the investigation off the poll loop.

    Investigating takes up to a minute, and the loop must not miss a container
    going down while it waits for the model to describe a different problem.
    """
    if not settings.discord_incident_channel_id:
        return
    task = asyncio.create_task(_open_incident(bot, name, promql))
    _incident_tasks.add(task)
    task.add_done_callback(_incident_tasks.discard)


async def _open_incident(bot, name: str, promql: str) -> None:
    """Post an agent investigation of a firing rule to the incident channel."""
    channel_id = settings.discord_incident_channel_id
    if not channel_id:
        return
    from agent.workflows import investigate as investigator

    try:
        body = await investigator.investigate(
            f"The PromQL alert rule `{name}` ({promql}) is firing. Check the affected "
            "services' logs and metrics and give a short likely cause and next steps."
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("incident investigation failed for %s: %s", name, exc)
        body = f"(could not investigate `{name}`: {exc})"
    chunks = [body[i : i + 3900] for i in range(0, len(body), 3900)] or [body]
    await discord_alert.post_report(channel_id, f"Incident — {name}", chunks, bot)


def start_monitor(bot):
    """Start the periodic poll that drives container and endpoint alerts."""

    @tasks.loop(seconds=max(settings.monitor_interval_seconds, 10))
    async def _poll():
        await _poll_containers(bot)
        await _poll_endpoints(bot)
        await _poll_alert_rules(bot)
        logger.debug(
            "poll done: %d container(s), %d endpoint(s)",
            len(_container_state),
            len(_endpoint_state),
        )

    _poll.start()
