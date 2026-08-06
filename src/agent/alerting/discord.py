"""Send alert messages to a Discord channel or user DM."""

import logging

import discord

from agent.bot.summarize import discordify
from agent.config.settings import settings
from agent.storage.repository import get_incident, update_incident_status, update_incident_thread_id
from agent.workflows.remediation import execute_approval, reject_approval, run_remediation_workflow

logger = logging.getLogger(__name__)

_COLORS = {"info": 0x3498DB, "warning": 0xE67E22, "critical": 0xE74C3C}


def _chunk(text: str, size: int = 1900) -> list[str]:
    """Split *text* into strings no longer than *size*, at newline boundaries."""
    parts: list[str] = []
    while text:
        if len(text) <= size:
            parts.append(text)
            break
        cut = text.rfind("\n", 0, size)
        if cut <= 0:
            cut = size
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return parts


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


class IncidentActionView(discord.ui.View):
    """Resolve / Fix buttons attached to an incident thread message.

    ``timeout=None`` makes the buttons persistent: they never expire while the
    bot is running, which matters because incidents are often handled long after
    the thread opens. ``!resolve`` / ``/resolve`` remain as fallbacks after a bot
    restart. **Fix** launches the remediation agent, which proposes a restart and
    posts an Approve/Reject view — a human must approve before anything executes.
    """

    def __init__(self, incident_id: str):
        super().__init__(timeout=None)
        self.incident_id = incident_id

    @discord.ui.button(label="Resolve", style=discord.ButtonStyle.success, emoji="✅")
    async def resolve(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if update_incident_status(self.incident_id, "resolved") is None:
            await interaction.response.send_message("Incident not found.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"Incident `{self.incident_id}` resolved.", ephemeral=True
        )

    @discord.ui.button(label="Fix", style=discord.ButtonStyle.danger, emoji="🔧")
    async def fix(self, interaction: discord.Interaction, _button: discord.ui.Button):
        """Launch the remediation agent against this incident's diagnosis.

        The remediator only *proposes* a restart; each proposal is posted with its own
        Approve/Reject view so a human gates execution.
        """
        incident = get_incident(self.incident_id)
        if incident is None:
            await interaction.response.send_message("Incident not found.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        result = await run_remediation_workflow(
            self.incident_id, incident["service"], incident["summary"]
        )
        await interaction.followup.send(f"Remediator:\n{result['summary'][:1900]}", ephemeral=True)
        for proposal in result["proposals"]:
            await interaction.followup.send(
                f"Proposed {proposal['action']} on `{proposal['container_name']}` "
                f"(approval `{proposal['id']}`). Approve to execute.",
                view=RemediationApprovalView(proposal["id"]),
            )
        if not result["proposals"]:
            await interaction.followup.send("No remediation proposed.", ephemeral=True)


class RemediationApprovalView(discord.ui.View):
    """Approve / Reject buttons for a proposed remediation action.

    Persistent (``timeout=None``) while the bot runs; ``!approve`` / ``!reject`` (and
    their slash forms) remain as fallback after a redeploy, mirroring the ack/resolve
    pattern. Approve is the only path that triggers the real Docker restart.
    """

    def __init__(self, approval_id: str):
        super().__init__(timeout=None)
        self.approval_id = approval_id

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, emoji="✅")
    async def approve(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        result = await execute_approval(self.approval_id)
        if result["ok"]:
            await interaction.followup.send(
                f"Approved — restart executed for `{self.approval_id}`.", ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"Could not approve `{self.approval_id}`: {result['error']}", ephemeral=True
            )

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.secondary, emoji="✋")
    async def reject(self, interaction: discord.Interaction, _button: discord.ui.Button):
        result = reject_approval(self.approval_id)
        if result["ok"]:
            await interaction.response.send_message(
                f"Rejected `{self.approval_id}`.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"Could not reject `{self.approval_id}`: {result['error']}", ephemeral=True
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
    # Discord caps message content at 2000 chars — split oversized summaries
    # at newline boundaries so the thread is readable. Discordify first so any
    # markdown tables/# headings in the diagnosis render as bold+bullets.
    for i, chunk in enumerate(_chunk(discordify(summary))):
        if i == 0:
            await thread.send(chunk)
        else:
            # Use embeds for continuation chunks to avoid noise in the thread.
            await thread.send(embed=discord.Embed(description=chunk[:4096]))
    await thread.send("Actions:", view=IncidentActionView(incident_id))
    update_incident_thread_id(incident_id, thread.id)
    return thread.id
