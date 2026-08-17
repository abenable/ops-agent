"""Discord slash (application) commands for the agent.

These are registered through discord.py's CommandTree so the bot exposes its
operations as slash commands (`/`).
"""

import discord
from discord import app_commands
from discord.ext import commands

from agent import investigate as investigator
from agent.bot.monitor import get_monitored_endpoints
from agent.bot.onboarding import post_project_notes
from agent.bot.summarize import clean
from agent.bot.utils import build_info_embed, format_container_list, split_discord_text
from agent.config.settings import settings
from agent.memory.repository import (
    add_watched_container,
    list_watched_containers,
    remove_watched_container,
)
from agent.tools import docker


async def _send_chunks(interaction: discord.Interaction, text: str) -> None:
    """Send a possibly-long result as one or more followup messages."""
    for chunk in split_discord_text(text) or ["(empty result)"]:
        await interaction.followup.send(chunk)


def setup_slash_commands(bot: commands.Bot) -> None:
    """Register slash commands on the bot's application-command tree."""

    @bot.tree.command(name="info", description="Show bot info and support links")
    async def slash_info(interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=build_info_embed(bot.user), ephemeral=True
        )

    @bot.tree.command(name="status", description="Summarize current infrastructure health")
    async def slash_status(interaction: discord.Interaction):
        await interaction.response.defer()
        items = await docker.list_containers(all_containers=True)
        sections: list[str] = []
        if items:
            sections.append(format_container_list(items))
        else:
            sections.append("Containers: none found (is the Docker socket mounted?)")
        endpoints = get_monitored_endpoints()
        if endpoints:
            lines = [f"- {name}: {url}" for name, url in endpoints.items()]
            sections.append("Monitored endpoints:\n" + "\n".join(lines))
        summary = await clean(
            "\n\n".join(sections),
            service="the infrastructure",
            action="summarize current infrastructure health (containers and monitored endpoints)",
        )
        await _send_chunks(interaction, summary)

    @bot.tree.command(name="investigate", description="Ask the agent to investigate an ops question")
    @app_commands.describe(question="What to look into, e.g. 'why is the api container restarting?'")
    async def slash_investigate(interaction: discord.Interaction, question: str):
        await interaction.response.defer()
        answer = await investigator.investigate(question)
        await _send_chunks(interaction, f"**Question:** {question}\n\n{answer}")

    @bot.tree.command(name="report", description="Generate a structured incident report for a service")
    @app_commands.describe(service="Service or container name (partial or separator-variant ok)")
    async def slash_report(interaction: discord.Interaction, service: str):
        await interaction.response.defer()
        text = await investigator.report(service)
        await _send_chunks(interaction, f"**Incident report — `{service}`**\n\n{text}")

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
                "No containers are being watched. Use `/watch <container>` to add one.",
                ephemeral=True,
            )
            return
        lines = ["**Watched containers**"] + [f"- `{name}`" for name in names]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

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
