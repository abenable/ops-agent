"""Discord bot client setup."""

import asyncio
import logging
import re
import sys

import discord
from discord.ext import commands

from agent.bot.digest import start_digests
from agent.bot.monitor import start_monitor
from agent.bot.slash import setup_slash_commands
from agent.config.settings import settings

logger = logging.getLogger(__name__)

# Guard on_ready re-entrancy after Discord gateway reconnects.
_setup_done = False


class DiscordLogHandler(logging.Handler):
    """Forward INFO+ logs to a Discord channel without blocking emit()."""

    def __init__(self, bot: discord.Client, channel_id: int):
        super().__init__(level=logging.INFO)
        self.bot = bot
        self.channel_id = channel_id
        self.queue: asyncio.Queue[str] = asyncio.Queue()

    def emit(self, record: logging.LogRecord) -> None:
        # Never route discord.py's own logs back into Discord (avoid loops)
        if record.name.startswith("discord"):
            return
        try:
            self.queue.put_nowait(self.format(record))
        except Exception:  # noqa: BLE001, S110 - logging.Handler.emit() must never raise
            pass  # pragma: no cover

    async def pump(self) -> None:
        # Resolve via cache, falling back to an API fetch — get_channel() is often
        # None right at on_ready before the channel cache is populated.
        channel = self.bot.get_channel(self.channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(self.channel_id)
            except Exception as exc:  # noqa: BLE001 - discord.py can raise many types here
                print(
                    f"Discord log channel {self.channel_id} unreachable: {exc}",
                    file=sys.stderr,
                )
                return

        # Confirm the wiring loudly so an empty channel means "nothing happening", not "broken".
        try:
            await channel.send("Log forwarding active (INFO and above).")
        except Exception as exc:  # noqa: BLE001 - discord.py can raise many types here
            print(f"Cannot send to Discord log channel: {exc}", file=sys.stderr)
            return

        while True:
            msg = await self.queue.get()
            try:
                await channel.send(f"```{msg[:1900]}```")
            except Exception as exc:  # noqa: BLE001 -- discord.py can raise many types here  # pragma: no cover
                # Write to stderr, not the root logger, to avoid re-entering this handler.
                print(f"Failed to send log to Discord: {exc}", file=sys.stderr)


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Quiet the HTTP transport loggers: they emit one INFO line per request
    # (every DeepSeek/Prometheus/Docker call), which floods the Discord log
    # channel and the console without being useful activity signal. Warnings
    # and errors still surface.
    for noisy in ("httpx", "httpx2"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


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

    bot = commands.Bot(command_prefix="", intents=intents)

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
        # Sync slash commands once on startup. Guild sync is faster during testing;
        # global sync is used when no guild id is configured.
        try:
            if settings.discord_guild_id:
                guild = discord.Object(id=settings.discord_guild_id)
                bot.tree.copy_global_to(guild=guild)
                synced = await bot.tree.sync(guild=guild)
            else:
                synced = await bot.tree.sync()
            logger.info("Synced %d slash command(s)", len(synced))
        except Exception as exc:  # noqa: BLE001 - discord.py can raise many types here
            logger.warning("Slash-command sync failed: %s", exc)

        _attach_discord_log_handler(bot)

    @bot.event
    async def on_message(message: discord.Message):
        # Ignore own messages and other bots.
        if message.author == bot.user or message.author.bot:
            return

        # DMs and mentions go to the agentic investigation loop.
        is_dm = message.guild is None
        if is_dm or bot.user in message.mentions:
            from agent import investigate as investigator
            from agent.bot.utils import split_discord_text

            question = re.sub(r"<@!?\d+>", "", message.content).strip()
            if not question:
                await message.reply("What should I look into? Try `/status` or `/investigate`.")
                return
            async with message.channel.typing():
                # Thread per channel (per DM), so follow-up questions keep context.
                answer = await investigator.investigate(question, thread_id=str(message.channel.id))
            chunks = split_discord_text(answer) or ["(empty answer)"]
            await message.reply(chunks[0])
            for chunk in chunks[1:]:
                await message.channel.send(chunk)

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
