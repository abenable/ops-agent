"""Send alert and report messages to a Discord channel."""

import logging

import discord

logger = logging.getLogger(__name__)

_COLORS = {"info": 0x3498DB, "warning": 0xE67E22, "critical": 0xE74C3C}


async def _resolve_channel(channel_id: int, bot: discord.Client) -> discord.abc.Messageable | None:
    """Resolve via the cache first, falling back to an API fetch — get_channel()
    is often None right after on_ready before the cache fills."""
    channel = bot.get_channel(channel_id)
    if channel is not None:
        return channel
    try:
        return await bot.fetch_channel(channel_id)
    except discord.DiscordException as exc:
        logger.warning("Channel %s unreachable: %s", channel_id, exc)
        return None


async def send_alert(
    channel_id: int,
    message: str,
    bot: discord.Client,
    *,
    severity: str = "info",
    title: str = "Alert",
) -> None:
    """Post a single rich embed alert to the given Discord channel.

    A bad channel id or a Discord API error is logged, never raised: callers
    run inside tasks.loop jobs that a raised exception would silently kill.
    """
    channel = await _resolve_channel(channel_id, bot)
    if channel is None:
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


async def post_report(channel_id: int, title: str, chunks: list[str], bot: discord.Client) -> None:
    """Post a (possibly multi-chunk) report as one unit.

    A forum channel gets one thread for the whole report: the first chunk
    opens it, the rest are follow-up messages inside it. A text channel gets
    one embed per chunk instead, since it has no thread to hold them.
    """
    channel = await _resolve_channel(channel_id, bot)
    if channel is None:
        return
    try:
        if isinstance(channel, discord.ForumChannel):
            opened = await channel.create_thread(
                name=title[:100],
                embed=discord.Embed(description=chunks[0][:4096], color=_COLORS["info"]),
            )
            for chunk in chunks[1:]:
                await opened.thread.send(embed=discord.Embed(description=chunk[:4096], color=_COLORS["info"]))
        else:
            for i, chunk in enumerate(chunks):
                embed = discord.Embed(
                    title=title if i == 0 else f"{title} (cont.)",
                    description=chunk[:4096],
                    color=_COLORS["info"],
                )
                await channel.send(embed=embed)
    except discord.DiscordException as exc:
        logger.warning("Failed to post report to channel %s: %s", channel_id, exc)
