"""Discord bot client setup."""

import asyncio
import logging
import sys

import discord
from discord.ext import commands

from agent.bot.digest import start_digests
from agent.bot.monitor import start_monitor
from agent.bot.slash import setup_slash_commands
from agent.config.settings import settings
from agent.memory import close_memory

logger = logging.getLogger(__name__)

_setup_done = False
_pump_task: asyncio.Task | None = None


class DiscordLogHandler(logging.Handler):
    """Forward INFO+ logs to a Discord channel without blocking emit()."""

    def __init__(self, bot: discord.Client, channel_id: int):
        super().__init__(level=logging.INFO)
        self.bot = bot
        self.channel_id = channel_id
        self.queue: asyncio.Queue[str] = asyncio.Queue()

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith("discord"):
            return
        try:
            self.queue.put_nowait(self.format(record))
        except Exception:  # noqa: BLE001, S110
            pass  # pragma: no cover

    async def pump(self) -> None:
        channel = self.bot.get_channel(self.channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(self.channel_id)
            except Exception as exc:  # noqa: BLE001
                print(
                    f"Discord log channel {self.channel_id} unreachable: {exc}",
                    file=sys.stderr,
                )
                return

        try:
            await channel.send("Log forwarding active (INFO and above).")
        except Exception as exc:  # noqa: BLE001
            print(f"Cannot send to Discord log channel: {exc}", file=sys.stderr)
            return

        while True:
            msg = await self.queue.get()
            try:
                await channel.send(f"```{msg[:1900]}```")
            except Exception as exc:  # noqa: BLE001
                print(f"Failed to send log to Discord: {exc}", file=sys.stderr)


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    for noisy in ("httpx", "httpx2"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _attach_discord_log_handler(bot: discord.Client) -> None:
    if not settings.discord_log_channel_id:
        return
    handler = DiscordLogHandler(bot, settings.discord_log_channel_id)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s\n%(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    global _pump_task
    _pump_task = asyncio.create_task(handler.pump())


class _Bot(commands.Bot):
    """The bot, plus the one shutdown step conversation memory needs."""

    async def close(self) -> None:
        await close_memory()
        await super().close()


def run_bot():
    intents = discord.Intents.default()
    intents.message_content = True

    bot = _Bot(command_prefix=commands.when_mentioned, intents=intents)

    @bot.event
    async def on_ready():
        global _setup_done
        logger.info("Bot logged in as %s", bot.user)

        if _setup_done:
            logger.info("Skipping duplicate setup after reconnect")
            return
        _setup_done = True

        start_monitor(bot)
        start_digests(bot)
        try:
            if settings.discord_guild_id:
                guild = discord.Object(id=settings.discord_guild_id)
                bot.tree.copy_global_to(guild=guild)
                synced = await bot.tree.sync(guild=guild)
            else:
                synced = await bot.tree.sync()
            logger.info("Synced %d slash command(s)", len(synced))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Slash-command sync failed: %s", exc)

        _attach_discord_log_handler(bot)

    @bot.event
    async def on_message(message: discord.Message):
        from agent.workflows.nl import handle_message

        await handle_message(bot, message)

    setup_slash_commands(bot)
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
