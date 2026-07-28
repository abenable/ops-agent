"""Send alert messages to a Discord channel or user DM."""

import logging

import discord

from agent.config.settings import settings
from agent.storage.repository import update_incident_status, update_incident_thread_id

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
        description=message,
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


class IncidentActionView(discord.ui.View):
    """Acknowledge / Resolve buttons attached to an incident thread message."""

    def __init__(self, incident_id: str):
        super().__init__(timeout=3600)
        self.incident_id = incident_id

    @discord.ui.button(label="Acknowledge", style=discord.ButtonStyle.primary, emoji="✋")
    async def ack(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if update_incident_status(self.incident_id, "acknowledged") is None:
            await interaction.response.send_message("Incident not found.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"Incident `{self.incident_id}` acknowledged.", ephemeral=True
        )

    @discord.ui.button(label="Resolve", style=discord.ButtonStyle.success, emoji="✅")
    async def resolve(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if update_incident_status(self.incident_id, "resolved") is None:
            await interaction.response.send_message("Incident not found.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"Incident `{self.incident_id}` resolved.", ephemeral=True
        )


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
    await thread.send("Actions:", view=IncidentActionView(incident_id))
    update_incident_thread_id(incident_id, thread.id)
    return thread.id
