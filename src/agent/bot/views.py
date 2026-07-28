"""Interactive Discord views (buttons, selects) for the bot."""

import discord

from agent.bot.summarize import clean
from agent.bot.utils import format_prometheus, format_status
from agent.tools.health import check_endpoint
from agent.tools.logs import get_recent_logs
from agent.tools.metrics import get_service_metrics
from agent.tools.services import get_service_status
from agent.workflows.incident import run_incident_workflow


class ServicePanelView(discord.ui.View):
    """Pick a monitored service/endpoint from a dropdown, then click an action."""

    def __init__(self, endpoints: dict[str, str]):
        super().__init__(timeout=300)
        self.endpoints = endpoints
        self.target = next(iter(endpoints), "")

        options = [discord.SelectOption(label=name) for name in endpoints]
        self.select = discord.ui.Select(
            placeholder="Pick a service…",
            options=options,
        )
        self.select.callback = self._on_select
        self.add_item(self.select)

    async def _on_select(self, interaction: discord.Interaction):
        self.target = self.select.values[0]
        await interaction.response.send_message(
            f"Selected `{self.target}`. Now click an action.",
            ephemeral=True,
        )

    @discord.ui.button(label="Status", style=discord.ButtonStyle.primary, emoji="📋")
    async def status(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if not self.target:
            await interaction.response.send_message("Pick a service first.", ephemeral=True)
            return
        result = await get_service_status(self.target)
        await interaction.response.send_message(format_status(result), ephemeral=True)

    @discord.ui.button(label="Health", style=discord.ButtonStyle.primary, emoji="🏥")
    async def health(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if not self.target:
            await interaction.response.send_message("Pick a service first.", ephemeral=True)
            return
        url = self.endpoints.get(self.target)
        if not url:
            await interaction.response.send_message(
                "No URL for this target.", ephemeral=True
            )
            return
        result = await check_endpoint(url)
        status = "Reachable" if result["reachable"] else "Unreachable"
        code = result.get("status_code")
        text = f"**{self.target}** — {status} ({code or 'no code'}) in {result['response_time_ms']} ms"
        await interaction.response.send_message(text, ephemeral=True)

    @discord.ui.button(label="Logs", style=discord.ButtonStyle.secondary, emoji="📜")
    async def logs(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if not self.target:
            await interaction.response.send_message("Pick a service first.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        text = await get_recent_logs(self.target, lines=20)
        summary = await clean(text, service=self.target, action="fetch recent logs")
        await interaction.followup.send(summary)

    @discord.ui.button(label="Metrics", style=discord.ButtonStyle.secondary, emoji="📈")
    async def metrics(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if not self.target:
            await interaction.response.send_message("Pick a service first.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        result = await get_service_metrics(self.target)
        summary = await clean(
            format_prometheus(result), service=self.target, action="fetch Prometheus metrics"
        )
        await interaction.followup.send(summary)

    @discord.ui.button(label="Incident", style=discord.ButtonStyle.danger, emoji="🚨")
    async def incident(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if not self.target:
            await interaction.response.send_message("Pick a service first.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        result = await run_incident_workflow(self.target)
        summary = result["summary"]
        text = f"Incident `{result['incident_id']}` for `{self.target}`\n\n{summary}"
        await interaction.followup.send(text[:2000])
