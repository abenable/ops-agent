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
    """Post a rich embed alert to the given Discord channel."""
    channel = bot.get_channel(channel_id)
    if channel is None:
        raise RuntimeError(f"Channel {channel_id} not found")
    embed = discord.Embed(
        title=title,
        description=message[:4096],
        color=_COLORS.get(severity, _COLORS["info"]),
    )
    await channel.send(embed=embed)


async def send_dm(
    bot: discord.Client,
    user_id: int,
    message: str,
) -> None:
    """Send a direct message to a user, swallowing errors caused by closed DMs."""
    try:
        user = await bot.fetch_user(user_id)
        await user.send(message[:2000])
    except discord.Forbidden:
        logger.warning("Cannot DM user %s (DMs disabled)", user_id)
    except discord.HTTPException as exc:
        logger.warning("Failed to DM user %s: %s", user_id, exc)
