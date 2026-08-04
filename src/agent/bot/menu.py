"""Interactive button/dropdown menu so users pick a container instead of typing args."""

import discord

from agent.bot.summarize import clean
from agent.bot.utils import format_prometheus, format_status
from agent.storage.repository import add_watched_container, is_watched, remove_watched_container
from agent.tools import docker
from agent.tools.metrics import get_service_metrics
from agent.tools.services import get_service_status


class _ActionView(discord.ui.View):
    """Read-only actions bound to one chosen container."""

    def __init__(self, container: str):
        super().__init__(timeout=120)
        self.container = container
        self._sync_watch_button()

    def _sync_watch_button(self) -> None:
        watching = is_watched(self.container)
        self.watch.label = "Unwatch" if watching else "Watch"
        self.watch.style = discord.ButtonStyle.danger if watching else discord.ButtonStyle.success
        self.watch.emoji = "🚫" if watching else "👁"

    @discord.ui.button(label="Watch", style=discord.ButtonStyle.success, emoji="👁", row=1)
    async def watch(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if is_watched(self.container):
            remove_watched_container(self.container)
            note = f"Stopped watching `{self.container}`."
        else:
            add_watched_container(self.container)
            note = f"👁 Now watching `{self.container}` — status updates will include it."
        self._sync_watch_button()
        await interaction.response.edit_message(
            content=f"**{self.container}** — choose an action:\n{note}",
            view=self,
        )

    @discord.ui.button(label="Status", style=discord.ButtonStyle.primary, emoji="📋")
    async def status(self, interaction: discord.Interaction, _button: discord.ui.Button):
        result = await get_service_status(self.container)
        await interaction.response.send_message(format_status(result), ephemeral=True)

    @discord.ui.button(label="Logs", style=discord.ButtonStyle.secondary, emoji="📜")
    async def logs(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        text = await docker.container_logs(self.container, tail=20)
        # Strip Docker's stream-framing control bytes so the summary stays clean.
        text = "".join(c for c in text if c.isprintable() or c in "\n\t")
        summary = await clean(text, service=self.container, action="fetch recent container logs")
        await interaction.followup.send(summary)

    @discord.ui.button(label="Metrics", style=discord.ButtonStyle.secondary, emoji="📈")
    async def metrics(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        result = await get_service_metrics(self.container)
        summary = await clean(
            format_prometheus(result), service=self.container, action="fetch Prometheus metrics"
        )
        await interaction.followup.send(summary)


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
