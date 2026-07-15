"""Background endpoint monitoring loop for Discord alerts and status updates."""

from discord.ext import tasks

from agent.alerting import discord as discord_alert
from agent.config.settings import settings
from agent.tools.health import check_endpoint
from agent.tools.sources.prometheus import query_prometheus
from agent.workflows.incident import run_incident_workflow

# url -> reachable (in-memory; fine for an MVP)
_last_state: dict[str, bool] = {}

# rule_name -> firing (in-memory; fine for an MVP)
_rule_state: dict[str, bool] = {}


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


def _alert_rules() -> dict[str, str]:
    out: dict[str, str] = {}
    for pair in settings.prometheus_alert_rules.split(","):
        if "=" in pair:
            name, expr = pair.split("=", 1)
            name = name.strip()
            expr = expr.strip()
            if name and expr:
                out[name] = expr
    return out


def get_alert_rules() -> dict[str, str]:
    """Public accessor used by the mention handler."""
    return _alert_rules()


async def _evaluate_rules(bot) -> None:
    """Evaluate PromQL alert rules and alert only on False -> True edges."""
    for rule_name, expr in _alert_rules().items():
        try:
            result = await query_prometheus(expr)
            firing = bool(result.get("data", {}).get("result"))
        except Exception:
            # ponytail: skip a rule when Prometheus is unreachable; endpoint poll still covers liveness
            continue

        prev = _rule_state.get(rule_name, False)
        if firing and not prev and settings.discord_alert_channel_id:
            await discord_alert.send_alert(
                settings.discord_alert_channel_id,
                f"PromQL alert `{rule_name}` firing: {expr}",
                bot,
                severity="critical",
                title=f"Alert: {rule_name}",
            )
            result_wf = await run_incident_workflow(rule_name)
            await discord_alert.open_incident_thread(
                bot, rule_name, result_wf["summary"], result_wf["incident_id"]
            )

        if prev and not firing and settings.discord_status_channel_id:
            await discord_alert.send_alert(
                settings.discord_status_channel_id,
                f"`{rule_name}` recovered",
                bot,
                severity="info",
                title="Recovered",
            )

        _rule_state[rule_name] = firing


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

    await _evaluate_rules(bot)


def start_monitor(bot):
    """Start the periodic endpoint poll."""

    @tasks.loop(seconds=max(settings.monitor_interval_seconds, 10))
    async def _poll():
        await _poll_once(bot)

    _poll.start()
