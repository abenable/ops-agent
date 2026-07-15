"""Discord bot client setup."""

import asyncio
import logging
import sys

import discord
from discord.ext import commands

from agent.bot.commands import setup_commands
from agent.bot.monitor import start_monitor
from agent.config.settings import settings
from agent.llm.client import get_llm

logger = logging.getLogger(__name__)


class DiscordLogHandler(logging.Handler):
    """Forward WARNING+ logs to a Discord channel without blocking emit()."""

    def __init__(self, bot: discord.Client, channel_id: int):
        super().__init__(level=logging.WARNING)
        self.bot = bot
        self.channel_id = channel_id
        self.queue: asyncio.Queue[str] = asyncio.Queue()

    def emit(self, record: logging.LogRecord) -> None:
        # Never route discord.py's own logs back into Discord (avoid loops)
        if record.name.startswith("discord"):
            return
        try:
            self.queue.put_nowait(self.format(record))
        except Exception:  # pragma: no cover
            pass

    async def pump(self) -> None:
        channel = self.bot.get_channel(self.channel_id)
        if channel is None:
            logger.warning("Discord log channel %s not found", self.channel_id)
            return
        while True:
            msg = await self.queue.get()
            try:
                await channel.send(f"```{msg[:1900]}```")
            except Exception as exc:  # pragma: no cover
                # Write to stderr, not the root logger, to avoid re-entering this handler.
                print(f"Failed to send log to Discord: {exc}", file=sys.stderr)


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _attach_discord_log_handler(bot: discord.Client) -> None:
    if not settings.discord_log_channel_id:
        return
    handler = DiscordLogHandler(bot, settings.discord_log_channel_id)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s\n%(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    asyncio.create_task(handler.pump())


def run_bot():
    intents = discord.Intents.default()
    intents.message_content = True

    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        logger.info("Bot logged in as %s", bot.user)
        start_monitor(bot)
        _attach_discord_log_handler(bot)

    @bot.event
    async def on_message(message: discord.Message):
        # Ignore own messages and other bots.
        if message.author == bot.user or message.author.bot:
            return

        # Let prefix commands through as usual.
        if message.content.strip().startswith("!"):
            await bot.process_commands(message)
            return

        # If the bot is pinged, answer via the configured LLM.
        if bot.user in message.mentions:
            cleaned = (
                message.content.replace(f"<@!{bot.user.id}>", "")
                .replace(f"<@{bot.user.id}>", "")
                .strip()
            )
            if not cleaned:
                cleaned = "Hello!"

            prompt = (
                "You are Oracle, a concise infrastructure-operations assistant.\n"
                f"User: {cleaned}\nOracle:"
            )
            try:
                response = await get_llm().ainvoke(prompt)
                await message.reply(response.content)
            except Exception as exc:  # pragma: no cover - LLM may be unavailable
                logger.warning("LLM mention response failed: %s", exc)
                await message.reply("My LLM is unreachable right now — try a `!` command instead.")

    setup_commands(bot)
    _setup_logging()

    if not settings.discord_bot_token:
        raise RuntimeError("DISCORD_BOT_TOKEN is not set")

    try:
        bot.run(settings.discord_bot_token)
    except discord.errors.PrivilegedIntentsRequired:
        logger.critical(
            "Privileged 'Message Content Intent' is not enabled for this bot. "
            "Enable it at https://discord.com/developers/applications"
        )
        raise SystemExit(1) from None
    except discord.errors.LoginFailure:
        logger.critical("Invalid DISCORD_BOT_TOKEN")
        raise SystemExit(1) from None
