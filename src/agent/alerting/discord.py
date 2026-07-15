"""Send alert messages to a Discord channel."""

import discord

from agent.config.settings import settings
from agent.storage.repository import update_incident_thread_id

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
        description=message,
        color=_COLORS.get(severity, _COLORS["info"]),
    )
    await channel.send(embed=embed)


async def open_incident_thread(
    bot: discord.Client,
    service: str,
    summary: str,
    incident_id: str,
) -> int | None:
    """Create a public thread in the incidents channel and record its id."""
    if settings.discord_incident_channel_id is None:
        return None
    channel = bot.get_channel(settings.discord_incident_channel_id)
    if channel is None:
        return None
    thread = await channel.create_thread(
        name=f"{service} — {incident_id}",
        type=discord.ChannelType.public_thread,
    )
    await thread.send(summary)
    update_incident_thread_id(incident_id, thread.id)
    return thread.id
