"""Send alert messages to a Discord channel."""

import discord


async def send_alert(channel_id: int, message: str, bot: discord.Client) -> None:
    """Post `message` to the given Discord channel."""
    channel = bot.get_channel(channel_id)
    if channel is None:
        raise RuntimeError(f"Channel {channel_id} not found")
    await channel.send(message)
