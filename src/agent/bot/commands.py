"""Discord chat commands for the agent."""

from pathlib import Path

import discord
import yaml
from discord.ext import commands

from agent.alerting import discord as discord_alert
from agent.bot.monitor import get_monitored_endpoints
from agent.bot.menu import MenuView
from agent.bot.utils import format_prometheus, format_status, split_discord_text
from agent.config.settings import settings
from agent.storage.repository import get_incident, update_incident_status
from agent.tools import docker
from agent.tools.health import check_endpoint
from agent.tools.logs import get_recent_logs
from agent.tools.metrics import get_service_metrics
from agent.tools.services import get_service_status
from agent.workflows.incident import run_ask_workflow, run_incident_workflow


def setup_commands(bot: commands.Bot) -> None:
    @bot.command(name="menu")
    async def menu(ctx: commands.Context):
        items = await docker.list_containers(all_containers=True)
        names = [docker.container_name(c) for c in items]
        if not names:
            await ctx.send("No containers found (is the Docker socket mounted?).")
            return
        await ctx.send("Pick a container:", view=MenuView(names))

    @bot.command(name="status")
    async def status(ctx: commands.Context, service: str):
        result = await get_service_status(service)
        await ctx.send(format_status(result))

    @bot.command(name="containers")
    async def containers(ctx: commands.Context):
        items = await docker.list_containers(all_containers=True)
        if not items:
            await ctx.send("No containers found (is the Docker socket mounted?).")
            return
        lines = ["**Containers**"]
        for c in items:
            dot = "🟢" if c.get("State") == "running" else "🔴"
            lines.append(f"{dot} {docker.container_name(c)} — {c.get('Status', '')}")
        for chunk in split_discord_text("\n".join(lines)):
            await ctx.send(chunk)

    @bot.command(name="logs")
    async def logs(ctx: commands.Context, service: str, lines: int = 10):
        result = await get_recent_logs(service, lines)
        for chunk in split_discord_text(result):
            await ctx.send(chunk)

    @bot.command(name="metrics")
    async def metrics(ctx: commands.Context, service: str):
        result = await get_service_metrics(service)
        await ctx.send(format_prometheus(result))

    @bot.command(name="incident")
    async def incident(ctx: commands.Context, service: str):
        result = await run_incident_workflow(service)
        summary = result["summary"]
        for chunk in split_discord_text(summary):
            await ctx.send(chunk)
        await ctx.send(f"Incident ID: {result['incident_id']}")

        await discord_alert.open_incident_thread(
            bot, service, summary, result["incident_id"]
        )

        if settings.discord_dm_user_id is not None:
            await discord_alert.send_dm(
                bot,
                settings.discord_dm_user_id,
                f"Incident {result['incident_id']} for `{service}`\n\n{summary[:1500]}",
            )

        if settings.discord_alert_channel_id is not None:
            # Keep the alert embed description short; Discord allows 4096 chars there.
            alert_message = f"Incident reported for {service}: {summary[:1000]}"
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
        for chunk in split_discord_text(result["summary"]):
            await ctx.send(chunk)

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

    @bot.command(name="ask")
    async def ask(ctx: commands.Context, *, question: str):
        try:
            answer = await run_ask_workflow(question)
        except Exception as exc:  # LLM may be offline
            answer = f"Ask failed: {exc}"
        for chunk in split_discord_text(answer):
            await ctx.send(chunk)
