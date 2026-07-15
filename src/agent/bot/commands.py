"""Discord chat commands for the agent."""

from pathlib import Path

import discord
import yaml
from discord.ext import commands

from agent.alerting import discord as discord_alert
from agent.bot.monitor import get_monitored_endpoints
from agent.config.settings import settings
from agent.storage.repository import get_incident, update_incident_status
from agent.tools.health import check_endpoint
from agent.tools.logs import get_recent_logs
from agent.tools.metrics import get_service_metrics
from agent.tools.services import get_service_status
from agent.workflows.incident import run_incident_workflow


def setup_commands(bot: commands.Bot) -> None:
    @bot.command(name="status")
    async def status(ctx: commands.Context, service: str):
        result = await get_service_status(service)
        await ctx.send(str(result))

    @bot.command(name="logs")
    async def logs(ctx: commands.Context, service: str, lines: int = 10):
        result = await get_recent_logs(service, lines)
        await ctx.send(result)

    @bot.command(name="metrics")
    async def metrics(ctx: commands.Context, service: str):
        result = await get_service_metrics(service)
        await ctx.send(str(result))

    @bot.command(name="incident")
    async def incident(ctx: commands.Context, service: str):
        result = await run_incident_workflow(service)
        reply = result["summary"] + f"\nIncident ID: {result['incident_id']}"
        await ctx.send(reply)

        await discord_alert.open_incident_thread(
            bot, service, result["summary"], result["incident_id"]
        )

        if settings.discord_alert_channel_id is not None:
            alert_message = f"Incident reported for {service}: {result['summary']}"
            await discord_alert.send_alert(
                settings.discord_alert_channel_id,
                alert_message,
                bot,
                severity="critical",
                title="Incident Reported",
            )

    @bot.command(name="ack")
    async def ack(ctx: commands.Context, incident_id: str):
        incident = update_incident_status(incident_id, "acknowledged")
        if incident is None:
            await ctx.send(f"Incident '{incident_id}' not found.")
            return
        await ctx.send(f"Incident {incident_id} acknowledged.")
        if incident.get("thread_id"):
            thread = bot.get_channel(incident["thread_id"])
            if thread:
                await thread.send("Incident acknowledged.")

    @bot.command(name="resolve")
    async def resolve(ctx: commands.Context, incident_id: str):
        incident = update_incident_status(incident_id, "resolved")
        if incident is None:
            await ctx.send(f"Incident '{incident_id}' not found.")
            return
        await ctx.send(f"Incident {incident_id} resolved.")
        if incident.get("thread_id"):
            thread = bot.get_channel(incident["thread_id"])
            if thread:
                await thread.send("Incident resolved.")

    @bot.command(name="scenario")
    async def scenario(ctx: commands.Context, name: str):
        if (
            settings.discord_test_scenarios_channel_id is not None
            and ctx.channel.id != settings.discord_test_scenarios_channel_id
        ):
            await ctx.send("This command only works in the test-scenarios channel.")
            return

        path = Path("scenarios") / f"{name}.yml"
        if not path.exists():
            await ctx.send(f"No scenario named '{name}'.")
            return

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        await ctx.send(
            f"▶ Simulating: {data['name']} — {data.get('symptom', '')}"
        )
        result = await run_incident_workflow(data["service"])
        await ctx.send(result["summary"])

    @bot.command(name="health")
    async def health(ctx: commands.Context, url: str):
        result = await check_endpoint(url)
        await ctx.send(
            f"{'Reachable' if result['reachable'] else 'Unreachable'} "
            f"({result.get('status_code')} in {result['response_time_ms']} ms)"
        )

    @bot.command(name="watching")
    async def watching(ctx: commands.Context):
        endpoints = get_monitored_endpoints()
        if not endpoints:
            await ctx.send("No endpoints are configured for monitoring.")
            return
        lines = ["**Monitored endpoints**"] + [f"- {name}: <{url}>" for name, url in endpoints.items()]
        await ctx.send("\n".join(lines))
