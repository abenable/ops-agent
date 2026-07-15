"""Discord chat commands for the agent."""

from discord.ext import commands

from agent.alerting import discord as discord_alert
from agent.config.settings import settings
from agent.tools.health import check_endpoint
from agent.tools.logs import get_recent_logs
from agent.tools.metrics import get_service_metrics
from agent.tools.services import get_service_status


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
        from agent.workflows.incident import run_incident_workflow

        result = await run_incident_workflow(service)
        reply = result["summary"] + f"\nIncident ID: {result['incident_id']}"
        await ctx.send(reply)

        if settings.discord_alert_channel_id is not None:
            alert_message = f"Incident reported for {service}: {result['summary']}"
            await discord_alert.send_alert(
                settings.discord_alert_channel_id, alert_message, bot
            )

    @bot.command(name="health")
    async def health(ctx: commands.Context, url: str):
        result = await check_endpoint(url)
        await ctx.send(
            f"{'Reachable' if result['reachable'] else 'Unreachable'} "
            f"({result.get('status_code')} in {result['response_time_ms']} ms)"
        )
