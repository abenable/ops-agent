"""Send alert messages to a Discord channel or user DM."""

import logging

import discord

logger = logging.getLogger(__name__)

_COLORS = {"info": 0x3498DB, "warning": 0xE67E22, "critical": 0xE74C3C}


async def send_alert(
    channel_id: int,
    message: str,
    bot: discord.Client,
    *,
    severity: str = "info",
    title: str = "Alert",
) -> None:
    """Post a rich embed alert to the given Discord channel.

    Resolves the channel via the cache first, falling back to an API fetch —
    get_channel() is often None right after on_ready before the cache fills.
    A bad channel id or a Discord API error is logged, never raised: callers
    run inside tasks.loop jobs that a raised exception would silently kill.
    """
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except discord.DiscordException as exc:
            logger.warning("Alert channel %s unreachable: %s", channel_id, exc)
            return
    embed = discord.Embed(
        title=title,
        description=message[:4096],
        color=_COLORS.get(severity, _COLORS["info"]),
    )
    try:
        await channel.send(embed=embed)
    except discord.DiscordException as exc:
        logger.warning("Failed to send alert to channel %s: %s", channel_id, exc)
