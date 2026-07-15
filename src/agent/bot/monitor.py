"""Background endpoint monitoring loop for Discord alerts and status updates."""

from discord.ext import tasks

from agent.alerting import discord as discord_alert
from agent.config.settings import settings
from agent.tools.health import check_endpoint
from agent.workflows.incident import run_incident_workflow

# url -> reachable (in-memory; fine for an MVP)
_last_state: dict[str, bool] = {}


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


async def _poll_once(bot) -> None:
    """Run one poll iteration across all monitored endpoints."""
    for name, url in _endpoints().items():
        res = await check_endpoint(url)
        # ponytail: treat 5xx as down; anything reachable under 500 is up
        up = res["reachable"] and (res["status_code"] or 599) < 500
        prev = _last_state.get(url)

        # #status-updates: post every observed transition
        if prev is not None and prev != up and settings.discord_status_channel_id:
            await discord_alert.send_alert(
                settings.discord_status_channel_id,
                f"{name} is now {'UP' if up else 'DOWN'}",
                bot,
                severity="info",
                title="Status change",
            )

        # #alerts: only escalate on healthy -> down transitions
        if prev is True and not up and settings.discord_alert_channel_id:
            await discord_alert.send_alert(
                settings.discord_alert_channel_id,
                f"{name} ({url}) is unreachable",
                bot,
                severity="critical",
                title="Service down",
            )
            # Create a threaded incident for the escalation
            result = await run_incident_workflow(name)
            await discord_alert.open_incident_thread(
                bot, name, result["summary"], result["incident_id"]
            )

        _last_state[url] = up


def start_monitor(bot):
    """Start the periodic endpoint poll."""

    @tasks.loop(seconds=max(settings.monitor_interval_seconds, 10))
    async def _poll():
        await _poll_once(bot)

    _poll.start()
