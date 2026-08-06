"""Clickable scenario runner for the #test-scenarios channel.

A persistent Discord message carries one button per ``scenarios/*.yml`` file;
clicking a button runs that scenario's incident workflow (with the scenario's
symptom as a hint) and posts the diagnosis into the channel, so an operator
can run a reproducible test with a single click instead of typing
``/scenario <name>``.

The panel is auto-created on startup when ``DISCORD_TEST_SCENARIOS_CHANNEL_ID``
is set, and re-registered on reconnect so its buttons keep working after a
redeploy. ``/scenarios`` refreshes the panel (e.g. after adding a scenario file).
"""

from __future__ import annotations

import logging
from pathlib import Path

import discord

from agent.bot.summarize import discordify
from agent.bot.utils import scenario_path, split_discord_text
from agent.config.settings import settings
from agent.workflows.incident import run_incident_workflow

logger = logging.getLogger(__name__)

_PANEL_MARKER = "\U0001F9EA **Scenario runner**"  # 🧪


def _available_scenarios() -> list[str]:
    """Return scenario names (file stems) under ``scenarios/``, sorted."""
    base = Path("scenarios")
    if not base.is_dir():
        return []
    return sorted(p.stem for p in base.glob("*.yml"))


async def _run_and_post(name: str, send) -> None:
    """Load a scenario, run its incident workflow, and post the result via *send*.

    *send* is an awaitable that takes a string and posts it (``ctx.send`` or
    ``interaction.followup.send``), so the button and the command share one path.
    """
    path = scenario_path(name)
    if path is None:
        await send(f"No scenario named '{name}'.")
        return
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    await send(f"\u25b6 Simulating: {data['name']} \u2014 {data.get('symptom', '')}")
    result = await run_incident_workflow(data["service"], hint=data.get("symptom"))
    for chunk in split_discord_text(discordify(result["summary"])):
        await send(chunk)


class ScenarioButton(discord.ui.Button):
    """One button per scenario; ``custom_id`` is stable across restarts."""

    def __init__(self, name: str):
        super().__init__(
            label=name,
            custom_id=f"scenario:{name}",
            style=discord.ButtonStyle.secondary,
        )
        self.scenario_name = name

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        await _run_and_post(self.scenario_name, interaction.followup.send)


class ScenarioPanelView(discord.ui.View):
    """A persistent row of scenario buttons, rebuilt from ``scenarios/*.yml``."""

    def __init__(self) -> None:
        super().__init__(timeout=None)
        for name in _available_scenarios():
            self.add_item(ScenarioButton(name))


async def ensure_scenario_panel(bot: discord.Client) -> None:
    """Create the runner panel in the test-scenarios channel if missing, or
    re-register its view on an existing panel so clicks survive a redeploy.
    """
    if settings.discord_test_scenarios_channel_id is None:
        return
    channel = bot.get_channel(settings.discord_test_scenarios_channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(settings.discord_test_scenarios_channel_id)
        except Exception as exc:
            logger.warning("Scenario channel %s unreachable: %s", settings.discord_test_scenarios_channel_id, exc)
            return

    # Reuse an existing panel if the bot posted one recently, to avoid spamming
    # the channel on every restart.
    try:
        hist = [m async for m in channel.history(limit=20, oldest_first=False)]
    except Exception as exc:
        logger.warning("Cannot read scenario channel history: %s", exc)
        return

    existing = next((m for m in hist if m.author.id == bot.user.id and m.content.startswith(_PANEL_MARKER)), None)
    if existing is not None:
        bot.add_view(ScenarioPanelView(), message_id=existing.id)
        return

    await channel.send(f"{_PANEL_MARKER} \u2014 click a scenario to simulate:", view=ScenarioPanelView())
