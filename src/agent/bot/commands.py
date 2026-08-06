"""Discord chat commands for the agent."""

import discord
import yaml
from discord.ext import commands

from agent.alerting import discord as discord_alert
from agent.alerting.discord import RemediationApprovalView
from agent.bot.history import ask_with_memory
from agent.bot.monitor import get_monitored_endpoints
from agent.bot.menu import MenuView
from agent.bot.onboarding import post_project_notes
from agent.bot.summarize import clean, discordify
from agent.bot.utils import build_info_embed, format_container_list, format_status, scenario_path, split_discord_text
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


def setup_commands(bot: commands.Bot) -> None:
    @bot.command(name="info")
    async def info(ctx: commands.Context):
        await ctx.send(embed=build_info_embed(bot.user))

    @bot.command(name="project-notes")
    async def project_notes(ctx: commands.Context):
        if settings.discord_project_notes_channel_id is None:
            await ctx.send("No #project-notes channel configured.")
            return
        await post_project_notes(bot)
        await ctx.send("Posted the project-notes embed to #project-notes.")

    @bot.command(name="menu")
    async def menu(ctx: commands.Context):
        items = await docker.list_containers(all_containers=True)
        names = [docker.container_name(c) for c in items]
        if not names:
            await ctx.send("No containers found (is the Docker socket mounted?).")
            return
        await ctx.send("Pick a container:", view=MenuView(names))

    @bot.command(name="panel")
    async def panel(ctx: commands.Context):
        endpoints = get_monitored_endpoints()
        if not endpoints:
            await ctx.send("No monitored endpoints configured for the panel.")
            return
        await ctx.send("Pick a service and action:", view=ServicePanelView(endpoints))

    @bot.command(name="llm")
    async def llm(ctx: commands.Context):
        view = LLMProviderView()
        await ctx.send(view._status_text(), view=view)

    @bot.command(name="status")
    async def status(ctx: commands.Context, service: str):
        result = await get_service_status(service)
        await ctx.send(format_status(result))

    @bot.command(name="containers")
    async def containers(ctx: commands.Context, raw: bool = False):
        items = await docker.list_containers(all_containers=True)
        if not items:
            await ctx.send("No containers found (is the Docker socket mounted?).")
            return
        if raw:
            for chunk in split_discord_text(format_container_list(items)):
                await ctx.send(chunk)
            return
        async with ctx.typing():
            summary = await clean(
                format_container_list(items),
                service="all containers",
                action="list Docker containers grouped by status",
            )
        await ctx.send(summary)

    @bot.command(name="logs")
    async def logs(ctx: commands.Context, service: str, lines: int = 10, raw: bool = False):
        async with ctx.typing():
            prompt = (
                f"Show the last ~{lines} log lines for the service matching '{service}'. "
                "Call list_services first to resolve the real container/endpoint name "
                "(the user may have typos or use different separators), then use query_loki "
                "or query_loki_range to fetch recent logs; fall back to docker_logs if Loki "
                "has nothing for it. Summarize the key lines briefly."
            )
            summary, raw_results = await run_scoped_investigation(prompt)
        out = raw_results if raw else discordify(summary or "(no logs)")
        for chunk in split_discord_text(out):
            await ctx.send(chunk)

    @bot.command(name="metrics")
    async def metrics(ctx: commands.Context, service: str, raw: bool = False):
        async with ctx.typing():
            prompt = (
                f"Report the current Prometheus metrics for the service matching '{service}'. "
                "Call list_services first to resolve the real container/endpoint name (the "
                "user may have typos or use different separators), then discover the available "
                "metric names with list_metric_names and label values with get_label_values, "
                "and query the most relevant current metrics with query_prometheus. "
                "Summarize the key values in a few lines; if no metrics exist, say so."
            )
            summary, raw_results = await run_scoped_investigation(prompt)
        out = raw_results if raw else discordify(summary or "(no metrics)")
        for chunk in split_discord_text(out):
            await ctx.send(chunk)

    @bot.command(name="incident")
    async def incident(ctx: commands.Context, service: str):
        result = await run_incident_workflow(service)
        summary = result["summary"]
        for chunk in split_discord_text(discordify(summary)):
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

        path = scenario_path(name)
        if path is None:
            await ctx.send(f"No scenario named '{name}'.")
            return

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        await ctx.send(
            f"▶ Simulating: {data['name']} — {data.get('symptom', '')}"
        )
        result = await run_incident_workflow(data["service"], hint=data.get("symptom"))
        for chunk in split_discord_text(discordify(result["summary"])):
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
        lines = ["**Monitored endpoints**"] + [
            f"- {name}: <{url}>" for name, url in endpoints.items()
        ]
        await ctx.send("\n".join(lines))

    @bot.command(name="watch")
    async def watch(ctx: commands.Context, container: str):
        """Add a container to the watch list; status updates will include it."""
        exact = await docker.resolve_container_name(container)
        if exact is None:
            await ctx.send(f"No container matching '{container}'.")
            return
        added = add_watched_container(exact)
        if added:
            await ctx.send(f"👁 Now watching `{exact}` — status updates will include it.")
        else:
            await ctx.send(f"`{exact}` is already being watched.")

    @bot.command(name="unwatch")
    async def unwatch(ctx: commands.Context, container: str):
        """Remove a container from the watch list."""
        removed = remove_watched_container(container)
        if removed:
            await ctx.send(f"Stopped watching `{container}`.")
        else:
            await ctx.send(f"`{container}` is not in the watch list.")

    @bot.command(name="watchlist")
    async def watchlist(ctx: commands.Context):
        """List the containers currently being watched."""
        names = list_watched_containers()
        if not names:
            await ctx.send(
                "No containers are being watched. Use `!watch <container>` to add one "
                "(or toggle it from the web dashboard)."
            )
            return
        lines = ["**Watched containers**"] + [f"- `{name}`" for name in names]
        await ctx.send("\n".join(lines))

    @bot.command(name="ask")
    async def ask(ctx: commands.Context, *, question: str):
        try:
            answer = await ask_with_memory(ctx.channel.id, question)
        except Exception as exc:  # LLM may be offline
            answer = f"Ask failed: {exc}"
        for chunk in split_discord_text(discordify(answer)):
            await ctx.send(chunk)

    @bot.command(name="remediate")
    async def remediate(ctx: commands.Context, incident_id: str):
        """Run the remediation agent against an existing incident's diagnosis.

        The remediator only proposes a restart; each proposal carries Approve/Reject
        buttons. Use !approve/!reject if the buttons are gone (e.g. after a redeploy).
        """
        incident = get_incident(incident_id)
        if incident is None:
            await ctx.send(f"Incident '{incident_id}' not found.")
            return
        async with ctx.typing():
            result = await run_remediation_workflow(
                incident_id, incident["service"], incident["summary"]
            )
        for chunk in split_discord_text(discordify(result["summary"])):
            await ctx.send(chunk)
        for proposal in result["proposals"]:
            await ctx.send(
                f"Proposed {proposal['action']} on `{proposal['container_name']}` "
                f"(approval `{proposal['id']}`).",
                view=RemediationApprovalView(proposal["id"]),
            )
        if not result["proposals"]:
            await ctx.send("No remediation proposed.")

    @bot.command(name="approve")
    async def approve(ctx: commands.Context, approval_id: str):
        """Approve and execute a proposed remediation action (button fallback)."""
        async with ctx.typing():
            result = await execute_approval(approval_id)
        if result["ok"]:
            await ctx.send(f"Approved — restart executed for `{approval_id}`.")
        else:
            await ctx.send(f"Could not approve `{approval_id}`: {result['error']}")

    @bot.command(name="reject")
    async def reject(ctx: commands.Context, approval_id: str):
        """Reject a proposed remediation action (button fallback)."""
        result = reject_approval(approval_id)
        if result["ok"]:
            await ctx.send(f"Rejected `{approval_id}`.")
        else:
            await ctx.send(f"Could not reject `{approval_id}`: {result['error']}")
