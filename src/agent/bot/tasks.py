"""Clickable task runner for the #test-tasks channel.

A persistent Discord message carries one button per ``agent/eval/tasks/*.yml`` file;
clicking a button runs the agentic investigation loop for that task's service
(with the task's symptom as a hint) and posts the summary into the channel, so an operator
can run a reproducible test with a single click instead of typing
``/task <name>``. The on-disk unit is a *task*; the operator verb is a
*task*.

The panel is auto-created on startup when ``DISCORD_TEST_TASKS_CHANNEL_ID``
is set, and re-registered on reconnect so its buttons keep working after a
redeploy. ``/tasks`` refreshes the panel (e.g. after adding a task file).
"""

from __future__ import annotations

import logging

import discord

from agent.bot.summarize import discordify
from agent.bot.utils import task_path, split_discord_text
from agent.config.settings import settings
from agent.tasks import available_tasks
from agent.workflows.incident import run_ask_workflow

logger = logging.getLogger(__name__)

_PANEL_MARKER = "\U0001F9EA **Task runner**"  # 🧪


async def _run_and_post(name: str, send) -> None:
    """Load a task, run the agentic investigation loop for it, and post the result via *send*.

    *send* is an awaitable that takes a string and posts it (``ctx.send`` or
    ``interaction.followup.send``), so the button and the command share one path.
    """
    path = task_path(name)
    if path is None:
        await send(f"No task named '{name}'.")
        return
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    await send(f"\u25b6 Simulating: {data['name']} \u2014 {data.get('symptom', '')}")
    prompt = f"Investigate service {data['service']}."
    if data.get("symptom"):
        prompt += f" Reported symptom: {data['symptom']}"
    summary = await run_ask_workflow(prompt)
    for chunk in split_discord_text(discordify(summary)):
        await send(chunk)


class TaskButton(discord.ui.Button):
    """One button per task; ``custom_id`` is stable across restarts."""

    def __init__(self, name: str):
        super().__init__(
            label=name,
            custom_id=f"task:{name}",
            style=discord.ButtonStyle.secondary,
        )
        self.task_name = name

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        await _run_and_post(self.task_name, interaction.followup.send)


class TaskPanelView(discord.ui.View):
    """A persistent row of task buttons, rebuilt from ``agent/eval/tasks/*.yml``."""

    def __init__(self) -> None:
        super().__init__(timeout=None)
        for name in available_tasks():
            self.add_item(TaskButton(name))


async def ensure_task_panel(bot: discord.Client) -> None:
    """Create the runner panel in the test-tasks channel if missing, or
    re-register its view on an existing panel so clicks survive a redeploy.
    """
    if settings.discord_test_tasks_channel_id is None:
        return
    channel = bot.get_channel(settings.discord_test_tasks_channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(settings.discord_test_tasks_channel_id)
        except Exception as exc:
            logger.warning("Task channel %s unreachable: %s", settings.discord_test_tasks_channel_id, exc)
            return

    # Reuse an existing panel if the bot posted one recently, to avoid spamming
    # the channel on every restart.
    try:
        hist = [m async for m in channel.history(limit=20, oldest_first=False)]
    except Exception as exc:
        logger.warning("Cannot read task channel history: %s", exc)
        return

    existing = next((m for m in hist if m.author.id == bot.user.id and m.content.startswith(_PANEL_MARKER)), None)
    if existing is not None:
        bot.add_view(TaskPanelView(), message_id=existing.id)
        return

    await channel.send(f"{_PANEL_MARKER} \u2014 click a task to simulate:", view=TaskPanelView())
