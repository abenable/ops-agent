"""Discord chat commands for the agent."""

from discord.ext import commands

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

        summary = run_incident_workflow(service)
        await ctx.send(summary)
