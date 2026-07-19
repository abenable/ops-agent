"""Interactive button/dropdown menu so users pick a container instead of typing args."""

import discord

from agent.bot.utils import format_prometheus, format_status
from agent.tools import docker
from agent.tools.metrics import get_service_metrics
from agent.tools.services import get_service_status


class _ActionView(discord.ui.View):
    """Read-only actions bound to one chosen container."""

    def __init__(self, container: str):
        super().__init__(timeout=120)
        self.container = container

    @discord.ui.button(label="Status", style=discord.ButtonStyle.primary, emoji="📋")
    async def status(self, interaction: discord.Interaction, _button: discord.ui.Button):
        result = await get_service_status(self.container)
        await interaction.response.send_message(format_status(result), ephemeral=True)

    @discord.ui.button(label="Logs", style=discord.ButtonStyle.secondary, emoji="📜")
    async def logs(self, interaction: discord.Interaction, _button: discord.ui.Button):
        text = await docker.container_logs(self.container, tail=20)
        # Strip Docker's stream-framing control bytes so the code block stays clean.
        clean = "".join(c for c in text if c.isprintable() or c in "\n\t")
        await interaction.response.send_message(f"```{clean[:1900] or 'No logs.'}```", ephemeral=True)

    @discord.ui.button(label="Metrics", style=discord.ButtonStyle.secondary, emoji="📈")
    async def metrics(self, interaction: discord.Interaction, _button: discord.ui.Button):
        result = await get_service_metrics(self.container)
        await interaction.response.send_message(format_prometheus(result), ephemeral=True)


class _ContainerSelect(discord.ui.Select):
    def __init__(self, names: list[str]):
        # Discord caps a select at 25 options.
        options = [discord.SelectOption(label=n) for n in names[:25]]
        super().__init__(placeholder="Pick a container…", options=options)

    async def callback(self, interaction: discord.Interaction):
        container = self.values[0]
        await interaction.response.send_message(
            f"**{container}** — choose an action:",
            view=_ActionView(container),
            ephemeral=True,
        )


class MenuView(discord.ui.View):
    def __init__(self, names: list[str]):
        super().__init__(timeout=180)
        self.add_item(_ContainerSelect(names))
