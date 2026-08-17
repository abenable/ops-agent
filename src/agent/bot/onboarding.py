"""Startup messages for the #welcome and #project-notes channels.

On connect the bot posts a help embed to #welcome (commands, channels) and an
architecture/design note to #project-notes. Both are pinned and refreshed in
place: the bot edits its existing pinned message if it already posted one, so
the channels don't accumulate stale copies across redeploys.
"""

from __future__ import annotations

import logging

import discord

from agent.config.settings import settings

logger = logging.getLogger(__name__)

_WELCOME_MARKER = "\U0001F44B **Oracle — Infrastructure Ops Agent**"  # 👋
_NOTES_MARKER = "\U0001F4D3 **Project notes — Marconi ops agent**"  # 📓

# Channel id -> human label, only those that are configured.
_CHANNELS = [
    ("alerts", "discord_alert_channel_id", "\U0001F6A8 down-alerts"),
    ("status-updates", "discord_status_channel_id", "\U0001F4CA up/down transitions + status snapshot"),
    ("agent-logs", "discord_log_channel_id", "\U0001F4DD live agent activity (tool calls, workflow)"),
]


def _configured_channels() -> list[str]:
    out = []
    for label, setting_key, desc in _CHANNELS:
        if getattr(settings, setting_key) is not None:
            out.append(f"`#{label}` \u2014 {desc}")
    return out or ["(no channels configured)"]


def build_welcome_embed(bot_user: discord.ClientUser | None) -> discord.Embed:
    name = bot_user.display_name if bot_user else "Oracle"
    embed = discord.Embed(
        title=f"{name} \u2014 Infrastructure Ops Agent",
        description=(
            "An AI-assisted monitor for this Docker stack. Ask it questions, "
            "check service health, or get incident summaries."
        ),
        color=0x3498DB,
    )
    embed.add_field(
        name="Commands (slash `/`)",
        inline=False,
        value=(
            "`status` `investigate <question>` `report <service>` `containers` "
            "`watch <name>` `watchlist` `unwatch <name>` `watching` `info`"
        ),
    )
    embed.add_field(name="Channels", inline=False, value="\n".join(_configured_channels()))
    embed.add_field(
        name="Try it",
        inline=False,
        value="Run `/status` for a health summary, or mention the bot with a question.",
    )
    return embed


def build_project_notes_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Project notes \u2014 Marconi ops agent",
        description=(
            "Self-hosted infrastructure-operations agent: a Discord bot that "
            "monitors this Docker stack and answers ops questions."
        ),
        color=0x2ECC71,
    )
    embed.add_field(
        name="Architecture",
        inline=False,
        value=(
            "**bot** (discord.py) runs a LangChain investigation loop with "
            "read-only Docker/Prometheus/Loki tools, backed by the self-hosted "
            "LLM. A background monitor loop polls containers and posts alerts; "
            "a SQLite store keeps the watched-container list."
        ),
    )
    embed.add_field(name="Channels", inline=False, value="\n".join(_configured_channels()))
    embed.add_field(
        name="LLM",
        inline=False,
        value=f"Model `{settings.llm_model}`.",
    )
    return embed


async def _post_or_refresh(
    bot: discord.Client, channel_id: int, marker: str, embed: discord.Embed
) -> None:
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except Exception as exc:
            logger.warning("Channel %s unreachable: %s", channel_id, exc)
            return

    try:
        async for m in channel.history(limit=20, oldest_first=False):
            if m.author.id == bot.user.id and m.content.startswith(marker):
                await m.edit(embed=embed)
                return
    except Exception as exc:
        logger.warning("Cannot edit existing %s message: %s", marker, exc)

    try:
        msg = await channel.send(marker, embed=embed)
        await msg.pin()
    except Exception as exc:
        logger.warning("Cannot post/pin %s message: %s", marker, exc)


async def post_welcome(bot: discord.Client) -> None:
    if settings.discord_welcome_channel_id is None:
        return
    await _post_or_refresh(bot, settings.discord_welcome_channel_id, _WELCOME_MARKER, build_welcome_embed(bot.user))


async def post_project_notes(bot: discord.Client) -> None:
    if settings.discord_project_notes_channel_id is None:
        return
    await _post_or_refresh(bot, settings.discord_project_notes_channel_id, _NOTES_MARKER, build_project_notes_embed())
