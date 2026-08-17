"""Tests for Discord alerting helpers."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from agent.alerting.discord import send_alert


def test_send_alert_uses_embed():
    channel = AsyncMock()
    bot = MagicMock()
    bot.get_channel.return_value = channel

    asyncio.run(send_alert(123, "the message", bot, severity="critical", title="Down"))

    bot.get_channel.assert_called_once_with(123)
    channel.send.assert_awaited_once()
    embed = channel.send.call_args.kwargs["embed"]
    assert embed.title == "Down"
    assert embed.description == "the message"
    assert embed.color.value == 0xE74C3C  # critical color


def test_send_alert_falls_back_to_fetch_channel():
    """get_channel() returns None before the cache fills; fetch via API instead."""
    import discord

    channel = AsyncMock()
    bot = MagicMock()
    bot.get_channel.return_value = None
    bot.fetch_channel = AsyncMock(return_value=channel)

    asyncio.run(send_alert(123, "msg", bot))

    bot.fetch_channel.assert_awaited_once_with(123)
    channel.send.assert_awaited_once()


def test_send_alert_never_raises_on_bad_channel():
    """A bad channel id must not raise — callers run inside tasks.loop jobs
    that a raised exception would silently kill."""
    import discord

    bot = MagicMock()
    bot.get_channel.return_value = None
    bot.fetch_channel = AsyncMock(
        side_effect=discord.HTTPException(MagicMock(), "unknown channel")
    )

    asyncio.run(send_alert(999, "msg", bot))  # must not raise


def test_send_alert_swallows_send_failure():
    import discord

    channel = AsyncMock()
    channel.send.side_effect = discord.HTTPException(MagicMock(), "missing access")
    bot = MagicMock()
    bot.get_channel.return_value = channel

    asyncio.run(send_alert(123, "msg", bot))  # must not raise
