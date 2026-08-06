"""Discord slash (application) commands for the agent.

These are registered through discord.py's CommandTree so the bot exposes both
prefix commands (`!`) and slash commands (`/`) for the same operations.
"""

import yaml
import discord
from discord import app_commands
from discord.ext import commands

from agent.alerting import discord as discord_alert
from agent.alerting.discord import RemediationApprovalView
from agent.bot.history import ask_with_memory
from agent.bot.menu import MenuView
from agent.bot.monitor import get_monitored_endpoints
from agent.bot.onboarding import post_project_notes
from agent.bot.summarize import clean, discordify
from agent.bot.utils import build_info_embed, format_container_list, format_status, scenario_path, split_discord_text
from agent.bot.scenarios import _PANEL_MARKER, ScenarioPanelView
from agent.bot.views import LLMProviderView, ServicePanelView
from agent.config.settings import settings
from agent.storage.repository import (
    add_watched_container,
    get_incident,
    list_watched_containers,
    remove_watched_container,
    update_incident_status,
)
from agent.tools import docker
from agent.tools.health import check_endpoint
from agent.tools.services import get_service_status
from agent.workflows.incident import run_incident_workflow, run_scoped_investigation
from agent.workflows.remediation import execute_approval, reject_approval, run_remediation_workflow


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
        await interaction.response.defer(ephemeral=True)
        result = await get_service_status(service)
        await interaction.followup.send(format_status(result))

    @bot.tree.command(name="containers", description="List Docker containers grouped by status")
    @app_commands.describe(raw="Show the full raw list instead of a summary")
    async def slash_containers(interaction: discord.Interaction, raw: bool = False):
        await interaction.response.defer(ephemeral=True)
        items = await docker.list_containers(all_containers=True)
        if not items:
            await interaction.followup.send(
                "No containers found (is the Docker socket mounted?).", ephemeral=True
            )
            return
        if raw:
            for chunk in split_discord_text(format_container_list(items)):
                await interaction.followup.send(chunk)
            return
        summary = await clean(
            format_container_list(items),
            service="all containers",
            action="list Docker containers grouped by status",
        )
        await interaction.followup.send(summary)

    @bot.tree.command(name="logs", description="Get recent logs for a service")
    @app_commands.describe(
        service="Service or container name",
        lines="Number of log lines",
        raw="Show the full raw logs instead of a summary",
    )
    async def slash_logs(
        interaction: discord.Interaction, service: str, lines: int = 10, raw: bool = False
    ):
        await interaction.response.defer(ephemeral=True)
        prompt = (
            f"Show the last ~{lines} log lines for the service matching '{service}'. "
            "Call list_services first to resolve the real container/endpoint name (the "
            "user may have typos or use different separators), then use query_loki or "
            "query_loki_range to fetch recent logs; fall back to docker_logs if Loki has "
            "nothing for it. Summarize the key lines briefly."
        )
        summary, raw_results = await run_scoped_investigation(prompt)
        out = raw_results if raw else discordify(summary or "(no logs)")
        for chunk in split_discord_text(out):
            await interaction.followup.send(chunk)

    @bot.tree.command(name="metrics", description="Get Prometheus metrics for a service")
    @app_commands.describe(service="Service or container name", raw="Show raw metrics instead of a summary")
    async def slash_metrics(interaction: discord.Interaction, service: str, raw: bool = False):
        await interaction.response.defer(ephemeral=True)
        prompt = (
            f"Report the current Prometheus metrics for the service matching '{service}'. "
            "Call list_services first to resolve the real container/endpoint name (the user "
            "may have typos or use different separators), then discover the available metric "
            "names with list_metric_names and label values with get_label_values, and query "
            "the most relevant current metrics with query_prometheus. Summarize the key "
            "values in a few lines; if no metrics exist, say so."
        )
        summary, raw_results = await run_scoped_investigation(prompt)
        out = raw_results if raw else discordify(summary or "(no metrics)")
        for chunk in split_discord_text(out):
            await interaction.followup.send(chunk)

    @bot.tree.command(name="health", description="Check the health of an HTTP endpoint")
    @app_commands.describe(url="URL to check")
    async def slash_health(interaction: discord.Interaction, url: str):
        await interaction.response.defer(ephemeral=True)
        result = await check_endpoint(url)
        status = "Reachable" if result["reachable"] else "Unreachable"
        code = result.get("status_code")
        text = f"{status} ({code or 'no code'}) in {result['response_time_ms']} ms"
        await interaction.followup.send(text)

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

    @bot.tree.command(name="watch", description="Add a container to the watch list")
    @app_commands.describe(container="Container name (partial or separator-variant ok)")
    async def slash_watch(interaction: discord.Interaction, container: str):
        await interaction.response.defer(ephemeral=True)
        exact = await docker.resolve_container_name(container)
        if exact is None:
            await interaction.followup.send(f"No container matching '{container}'.", ephemeral=True)
            return
        added = add_watched_container(exact)
        if added:
            await interaction.followup.send(
                f"👁 Now watching `{exact}` — status updates will include it.", ephemeral=True
            )
        else:
            await interaction.followup.send(f"`{exact}` is already being watched.", ephemeral=True)

    @bot.tree.command(name="unwatch", description="Remove a container from the watch list")
    @app_commands.describe(container="Container name to stop watching")
    async def slash_unwatch(interaction: discord.Interaction, container: str):
        removed = remove_watched_container(container)
        if removed:
            await interaction.response.send_message(
                f"Stopped watching `{container}`.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"`{container}` is not in the watch list.", ephemeral=True
            )

    @bot.tree.command(name="watchlist", description="List the containers currently being watched")
    async def slash_watchlist(interaction: discord.Interaction):
        names = list_watched_containers()
        if not names:
            await interaction.response.send_message(
                "No containers are being watched. Use `/watch <container>` to add one "
                "(or toggle it from the web dashboard).",
                ephemeral=True,
            )
            return
        lines = ["**Watched containers**"] + [f"- `{name}`" for name in names]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @bot.tree.command(name="menu", description="Pick a container from a dropdown")
    async def slash_menu(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        items = await docker.list_containers(all_containers=True)
        names = [docker.container_name(c) for c in items]
        if not names:
            await interaction.followup.send(
                "No containers found (is the Docker socket mounted?).", ephemeral=True
            )
            return
        await interaction.followup.send("Pick a container:", view=MenuView(names))

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

    @bot.tree.command(name="llm", description="Switch the active LLM provider (Ollama / vLLM / Legacy)")
    async def slash_llm(interaction: discord.Interaction):
        view = LLMProviderView()
        await interaction.response.send_message(
            view._status_text(), view=view, ephemeral=True
        )

    @bot.tree.command(name="incident", description="Run the incident investigation workflow")
    @app_commands.describe(service="Service or container to investigate")
    async def slash_incident(interaction: discord.Interaction, service: str):
        await interaction.response.defer(ephemeral=True)
        result = await run_incident_workflow(service)
        summary = result["summary"]
        for chunk in split_discord_text(discordify(summary)):
            await interaction.followup.send(chunk)
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

        path = scenario_path(name)
        if path is None:
            await interaction.response.send_message(
                f"No scenario named '{name}'.", ephemeral=True
            )
            return

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        await interaction.response.send_message(
            f"▶ Simulating: {data['name']} — {data.get('symptom', '')}"
        )
        result = await run_incident_workflow(data["service"], hint=data.get("symptom"))
        for chunk in split_discord_text(discordify(result["summary"])):
            await interaction.followup.send(chunk)

    @bot.tree.command(name="scenarios", description="Re-post the clickable scenario runner panel")
    async def slash_scenarios(interaction: discord.Interaction):
        if (
            settings.discord_test_scenarios_channel_id is not None
            and interaction.channel_id != settings.discord_test_scenarios_channel_id
        ):
            await interaction.response.send_message(
                "This command only works in the test-scenarios channel.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            f"{_PANEL_MARKER} — click a scenario to simulate:", view=ScenarioPanelView()
        )

    @bot.tree.command(name="project-notes", description="Post or refresh the project-notes embed in #project-notes")
    async def slash_project_notes(interaction: discord.Interaction):
        if settings.discord_project_notes_channel_id is None:
            await interaction.response.send_message(
                "No #project-notes channel configured.", ephemeral=True
            )
            return
        await post_project_notes(bot)
        await interaction.response.send_message(
            "Posted the project-notes embed to #project-notes.", ephemeral=True
        )

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
            answer = await ask_with_memory(interaction.channel_id, question)
        except Exception as exc:
            answer = f"Ask failed: {exc}"
        for chunk in split_discord_text(discordify(answer)):
            await interaction.followup.send(chunk)

    @bot.tree.command(name="remediate", description="Run the remediation agent on an existing incident")
    @app_commands.describe(incident_id="Incident ID to remediate")
    async def slash_remediate(interaction: discord.Interaction, incident_id: str):
        await interaction.response.defer(ephemeral=True)
        incident = get_incident(incident_id)
        if incident is None:
            await interaction.followup.send(f"Incident '{incident_id}' not found.", ephemeral=True)
            return
        result = await run_remediation_workflow(
            incident_id, incident["service"], incident["summary"]
        )
        for chunk in split_discord_text(discordify(result["summary"])):
            await interaction.followup.send(chunk, ephemeral=True)
        for proposal in result["proposals"]:
            await interaction.followup.send(
                f"Proposed {proposal['action']} on `{proposal['container_name']}` "
                f"(approval `{proposal['id']}`).",
                view=RemediationApprovalView(proposal["id"]),
                ephemeral=True,
            )
        if not result["proposals"]:
            await interaction.followup.send("No remediation proposed.", ephemeral=True)

    @bot.tree.command(name="approve", description="Approve and execute a proposed remediation action")
    @app_commands.describe(approval_id="Approval ID")
    async def slash_approve(interaction: discord.Interaction, approval_id: str):
        await interaction.response.defer(ephemeral=True)
        result = await execute_approval(approval_id)
        if result["ok"]:
            await interaction.followup.send(
                f"Approved — restart executed for `{approval_id}`.", ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"Could not approve `{approval_id}`: {result['error']}", ephemeral=True
            )

    @bot.tree.command(name="reject", description="Reject a proposed remediation action")
    @app_commands.describe(approval_id="Approval ID")
    async def slash_reject(interaction: discord.Interaction, approval_id: str):
        result = reject_approval(approval_id)
        if result["ok"]:
            await interaction.response.send_message(
                f"Rejected `{approval_id}`.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"Could not reject `{approval_id}`: {result['error']}", ephemeral=True
            )

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
