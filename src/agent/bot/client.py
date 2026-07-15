"""Discord bot client setup."""

import discord
from discord.ext import commands

from agent.bot.commands import setup_commands
from agent.config.settings import settings


def run_bot():
    intents = discord.Intents.default()
    intents.message_content = True

    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        print(f"Bot logged in as {bot.user}")  # noqa: T201

    setup_commands(bot)

    if not settings.discord_bot_token:
        raise RuntimeError("DISCORD_BOT_TOKEN is not set")

    bot.run(settings.discord_bot_token)
