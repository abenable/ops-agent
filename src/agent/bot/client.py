"""Discord bot client setup."""

import asyncio
import logging
import sys

import discord
from discord.ext import commands

from agent.bot.commands import setup_commands
from agent.bot.monitor import get_alert_rules, get_monitored_endpoints, start_monitor
from agent.bot.utils import split_discord_text
from agent.config.settings import settings
from agent.bot.slash import setup_slash_commands
from agent.workflows.incident import llm_supports_tool_calls, run_ask_workflow

logger = logging.getLogger(__name__)

# Guard on_ready re-entrancy after Discord gateway reconnects.
_setup_done = False


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
        # Resolve via cache, falling back to an API fetch — get_channel() is often
        # None right at on_ready before the channel cache is populated.
        channel = self.bot.get_channel(self.channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(self.channel_id)
            except Exception as exc:
                print(
                    f"Discord log channel {self.channel_id} unreachable: {exc}",
                    file=sys.stderr,
                )
                return

        # Confirm the wiring loudly so an empty channel means "no warnings", not "broken".
        try:
            await channel.send("Log forwarding active (WARNING and above).")
        except Exception as exc:
            print(f"Cannot send to Discord log channel: {exc}", file=sys.stderr)
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


def _environment_context() -> str:
    endpoints = get_monitored_endpoints()
    endpoint_lines = [f"- {name}: {url}" for name, url in endpoints.items()]
    rules = get_alert_rules()
    rule_lines = [f"- {name}: {expr}" for name, expr in rules.items()]
    return (
        "Environment context:\n"
        f"Monitored endpoints:\n{'\n'.join(endpoint_lines) if endpoint_lines else '- none configured'}\n"
        f"PromQL alert rules:\n{'\n'.join(rule_lines) if rule_lines else '- none configured'}\n"
        f"Alert channel: {settings.discord_alert_channel_id or 'not set'}\n"
        f"Status channel: {settings.discord_status_channel_id or 'not set'}\n"
        f"Incident channel: {settings.discord_incident_channel_id or 'not set'}\n"
        f"Prometheus: {settings.prometheus_url}\n"
        f"Loki: {settings.loki_url}\n"
        "Available tools: menu, status, containers, logs, metrics, health, incident, scenario, ack, resolve, watching"
    )


def run_bot():
    intents = discord.Intents.default()
    intents.message_content = True

    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        global _setup_done
        logger.info("Bot logged in as %s", bot.user)

        if _setup_done:
            logger.info("Skipping duplicate setup after reconnect")
            return
        _setup_done = True

        start_monitor(bot)
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
        except Exception as exc:
            logger.warning("Slash-command sync failed: %s", exc)

        _attach_discord_log_handler(bot)

        # Check LLM capability in the background; a slow LLM probe should not delay
        # the gateway heartbeat/ready acknowledgement.
        async def _check_tools():
            if not await llm_supports_tool_calls():
                logger.warning(
                    "Configured LLM does not appear to support OpenAI-style tool calls. "
                    "Investigations will fall back to static summaries; tool-calling will not work."
                )

        asyncio.create_task(_check_tools())

    @bot.event
    async def on_command_error(ctx: commands.Context, error: commands.CommandError):
        """Surface common command failures to the user instead of crashing silently."""
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(f"You need permission: `{', '.join(error.missing_permissions)}`")
            return
        if isinstance(error, commands.BotMissingPermissions):
            await ctx.send(f"I need permission: `{', '.join(error.missing_permissions)}`")
            return
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"Cooldown: try again in {error.retry_after:.1f}s.")
            return
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"Missing argument: `{error.param.name}`. Check `!help {ctx.command}`.")
            return
        logger.exception("Command error: %s", error)
        await ctx.send(f"Command failed: `{error}`")

    @bot.event
    async def on_message(message: discord.Message):
        # Ignore own messages and other bots.
        if message.author == bot.user or message.author.bot:
            return

        # Let prefix commands through as usual (works in DMs and guilds).
        if message.content.strip().startswith("!"):
            await bot.process_commands(message)
            return

        # Respond to DMs and @mentions via the agentic loop.
        is_dm = message.guild is None
        if is_dm or bot.user in message.mentions:
            cleaned = (
                message.content.replace(f"<@!{bot.user.id}>", "")
                .replace(f"<@{bot.user.id}>", "")
                .strip()
            )
            if not cleaned:
                await message.reply(
                    "Hey! Ask me anything about the infrastructure, or type `!info` for commands."
                )
                return

            prompt = (
                "You are Oracle, a friendly infrastructure-operations assistant. "
                "Use the environment context below, and the read-only Prometheus/Loki tools if needed. "
                "Be brief and conversational; if you don't know, say so.\n\n"
                f"{_environment_context()}\n\n"
                f"Question: {cleaned}"
            )
            try:
                answer = await run_ask_workflow(prompt)
            except Exception as exc:  # pragma: no cover
                logger.warning("Mention response failed: %s", exc)
                answer = "My agent is unreachable right now — try a `!` command instead."

            chunks = split_discord_text(answer)
            if not chunks:
                await message.reply("(no response)")
                return
            await message.reply(chunks[0])
            for chunk in chunks[1:]:
                await message.channel.send(chunk)

    setup_commands(bot)
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
