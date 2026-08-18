"""Natural-language questions: DMs and @mentions, routed through the same
investigation loop as ``/investigate``.

Used to live as a closure inside ``bot.client.run_bot`` — untestable, and any
exception it raised was swallowed by discord.py's default error handler and
logged to ``discord.client``, a logger this bot deliberately filters out of
its own Discord log channel (see ``DiscordLogHandler.emit``). Net effect: a
failure here looked like the bot silently not responding. Pulling it out
into a plain function lets us wrap it in a try/except that always replies.
"""

import logging
import re

import discord

from agent.bot.utils import split_discord_text
from agent.workflows import investigate as investigator

logger = logging.getLogger(__name__)

_MENTION_RE = re.compile(r"<@!?\d+>")


async def handle_message(bot: discord.Client, message: discord.Message) -> None:
    """Answer a DM or @mention; no-op for anything else."""
    if message.author == bot.user or message.author.bot:
        return

    is_dm = message.guild is None
    if not (is_dm or bot.user in message.mentions):
        return

    question = _MENTION_RE.sub("", message.content).strip()
    if not question:
        await message.reply("What should I look into? Try `/status` or `/investigate`.")
        return

    try:
        async with message.channel.typing():
            # Thread per channel (per DM), so follow-up questions keep context.
            answer = await investigator.investigate(question, thread_id=str(message.channel.id))
    except Exception as exc:  # noqa: BLE001 - must always answer, never go silent
        logger.exception("natural-language handling failed")
        await message.reply(f"Something went wrong answering that: {exc}")
        return

    chunks = split_discord_text(answer) or ["(empty answer)"]
    await message.reply(chunks[0])
    for chunk in chunks[1:]:
        await message.channel.send(chunk)
