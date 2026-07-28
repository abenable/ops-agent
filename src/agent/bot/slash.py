"""Discord slash (application) commands for the agent.

These are registered through discord.py's CommandTree so the bot exposes both
prefix commands (`!`) and slash commands (`/`) for the same operations.
"""

from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from agent.alerting import discord as discord_alert
from agent.bot.menu import MenuView
from agent.bot.monitor import get_monitored_endpoints
from agent.bot.utils import build_info_embed, format_prometheus, format_status, split_discord_text
from agent.bot.views import ServicePanelView
from agent.config.settings import settings
from agent.storage.repository import get_incident, update_incident_status
from agent.tools import docker
from agent.tools.health import check_endpoint
from agent.tools.logs import get_recent_logs
from agent.tools.metrics import get_service_metrics
from agent.tools.services import get_service_status
from agent.workflows.incident import run_ask_workflow, run_incident_workflow


def setup_slash_commands(bot: commands.Bot) -> None:
    """Register slash commands on the bot's application-command tree."""

    @bot.tree.command(name="info", description="Show bot info and support links")
    async def slash_info(interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=build_info_embed(bot.user), ephemeral=True
        )

    @bot.tree.command(name="status", description="Get the status of a service")
    @app_commands.describe(service="Service or container name")
    async def slash_status(interaction: discord.Interaction, service: str):
        result = await get_service_status(service)
        await interaction.response.send_message(
            format_status(result), ephemeral=True
        )

    @bot.tree.command(name="containers", description="List running Docker containers")
    async def slash_containers(interaction: discord.Interaction):
        items = await docker.list_containers(all_containers=True)
        if not items:
            await interaction.response.send_message(
                "No containers found (is the Docker socket mounted?).",
                ephemeral=True,
            )
            return
        lines = ["**Containers**"]
        for c in items:
            dot = "🟢" if c.get("State") == "running" else "🔴"
            lines.append(f"{dot} {docker.container_name(c)} — {c.get('Status', '')}")
        text = "\n".join(lines)
        for chunk in split_discord_text(text):
            await interaction.response.send_message(chunk, ephemeral=True)
            break

    @bot.tree.command(name="logs", description="Get recent logs for a service")
    @app_commands.describe(service="Service or container name", lines="Number of log lines")
    async def slash_logs(interaction: discord.Interaction, service: str, lines: int = 10):
        result = await get_recent_logs(service, lines)
        for chunk in split_discord_text(result):
            await interaction.response.send_message(f"```{chunk[:1900]}```", ephemeral=True)
            break

    @bot.tree.command(name="metrics", description="Get Prometheus metrics for a service")
    @app_commands.describe(service="Service or container name")
    async def slash_metrics(interaction: discord.Interaction, service: str):
        result = await get_service_metrics(service)
        await interaction.response.send_message(
            format_prometheus(result), ephemeral=True
        )

    @bot.tree.command(name="health", description="Check the health of an HTTP endpoint")
    @app_commands.describe(url="URL to check")
    async def slash_health(interaction: discord.Interaction, url: str):
        result = await check_endpoint(url)
        status = "Reachable" if result["reachable"] else "Unreachable"
        code = result.get("status_code")
        text = (
            f"{status} ({code or 'no code'}) in {result['response_time_ms']} ms"
        )
        await interaction.response.send_message(text, ephemeral=True)

    @bot.tree.command(name="watching", description="List configured monitoring endpoints")
    async def slash_watching(interaction: discord.Interaction):
        endpoints = get_monitored_endpoints()
        if not endpoints:
            await interaction.response.send_message(
                "No endpoints are configured for monitoring.", ephemeral=True
            )
            return
        lines = ["**Monitored endpoints**"] + [
            f"- {name}: <{url}>" for name, url in endpoints.items()
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @bot.tree.command(name="menu", description="Pick a container from a dropdown")
    async def slash_menu(interaction: discord.Interaction):
        items = await docker.list_containers(all_containers=True)
        names = [docker.container_name(c) for c in items]
        if not names:
            await interaction.response.send_message(
                "No containers found (is the Docker socket mounted?).",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "Pick a container:", view=MenuView(names), ephemeral=True
        )

    @bot.tree.command(name="panel", description="Pick a monitored service and run an action")
    async def slash_panel(interaction: discord.Interaction):
        endpoints = get_monitored_endpoints()
        if not endpoints:
            await interaction.response.send_message(
                "No monitored endpoints configured for the panel.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "Pick a service and action:", view=ServicePanelView(endpoints), ephemeral=True
        )

    @bot.tree.command(name="incident", description="Run the incident investigation workflow")
    @app_commands.describe(service="Service or container to investigate")
    async def slash_incident(interaction: discord.Interaction, service: str):
        await interaction.response.defer(ephemeral=True)
        result = await run_incident_workflow(service)
        summary = result["summary"]
        for chunk in split_discord_text(summary):
            await interaction.followup.send(chunk)
            break
        await interaction.followup.send(f"Incident ID: {result['incident_id']}")

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
            alert_message = f"Incident reported for {service}: {summary[:1000]}"
            await discord_alert.send_alert(
                settings.discord_alert_channel_id,
                alert_message,
                bot,
                severity="critical",
                title="Incident Reported",
            )

    @bot.tree.command(name="scenario", description="Run a simulated scenario from scenarios/<name>.yml")
    @app_commands.describe(name="Scenario file name (without .yml)")
    async def slash_scenario(interaction: discord.Interaction, name: str):
        if (
            settings.discord_test_scenarios_channel_id is not None
            and interaction.channel_id != settings.discord_test_scenarios_channel_id
        ):
            await interaction.response.send_message(
                "This command only works in the test-scenarios channel.",
                ephemeral=True,
            )
            return

        path = Path("scenarios") / f"{name}.yml"
        if not path.exists():
            await interaction.response.send_message(
                f"No scenario named '{name}'.", ephemeral=True
            )
            return

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        await interaction.response.send_message(
            f"▶ Simulating: {data['name']} — {data.get('symptom', '')}"
        )
        result = await run_incident_workflow(data["service"])
        for chunk in split_discord_text(result["summary"]):
            await interaction.followup.send(chunk)
            break

    @bot.tree.command(name="ack", description="Acknowledge a stored incident")
    @app_commands.describe(incident_id="Incident ID")
    async def slash_ack(interaction: discord.Interaction, incident_id: str):
        incident = update_incident_status(incident_id, "acknowledged")
        if incident is None:
            await interaction.response.send_message(
                f"Incident '{incident_id}' not found.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"Incident {incident_id} acknowledged.", ephemeral=True
        )
        if incident.get("thread_id"):
            thread = bot.get_channel(incident["thread_id"])
            if thread:
                await thread.send("Incident acknowledged.")

    @bot.tree.command(name="resolve", description="Resolve a stored incident")
    @app_commands.describe(incident_id="Incident ID")
    async def slash_resolve(interaction: discord.Interaction, incident_id: str):
        incident = update_incident_status(incident_id, "resolved")
        if incident is None:
            await interaction.response.send_message(
                f"Incident '{incident_id}' not found.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"Incident {incident_id} resolved.", ephemeral=True
        )
        if incident.get("thread_id"):
            thread = bot.get_channel(incident["thread_id"])
            if thread:
                await thread.send("Incident resolved.")

    @bot.tree.command(name="ask", description="Ask the agent a free-form question")
    @app_commands.describe(question="What do you want to ask?")
    async def slash_ask(interaction: discord.Interaction, question: str):
        await interaction.response.defer(ephemeral=True)
        try:
            answer = await run_ask_workflow(question)
        except Exception as exc:
            answer = f"Ask failed: {exc}"
        for chunk in split_discord_text(answer):
            await interaction.followup.send(chunk)
            break

    async def on_app_command_error(
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.CommandOnCooldown):
            msg = f"Cooldown: try again in {error.retry_after:.1f}s."
        elif isinstance(error, app_commands.MissingPermissions):
            msg = f"You need permission: `{', '.join(error.missing_permissions)}`"
        elif isinstance(error, app_commands.BotMissingPermissions):
            msg = f"I need permission: `{', '.join(error.missing_permissions)}`"
        elif isinstance(error, app_commands.CheckFailure):
            msg = "You can't use this command here."
        else:
            msg = f"Slash command failed: {error}"

        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

    bot.tree.on_error = on_app_command_error
