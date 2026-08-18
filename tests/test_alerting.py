"""Tests for Discord alerting helpers."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from agent.alerting.discord import post_report, send_alert


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


def test_post_report_forum_channel_opens_one_thread_with_all_chunks():
    import discord

    thread = AsyncMock()
    thread.id = 999888777
    opened = MagicMock(thread=thread)
    channel = MagicMock(spec=discord.ForumChannel)
    channel.create_thread = AsyncMock(return_value=opened)
    bot = MagicMock()
    bot.get_channel.return_value = channel

    result = asyncio.run(post_report(123, "Weekly report", ["chunk one", "chunk two"], bot))

    channel.create_thread.assert_awaited_once()
    kwargs = channel.create_thread.call_args.kwargs
    assert kwargs["name"] == "Weekly report"
    assert kwargs["embed"].description == "chunk one"
    thread.send.assert_awaited_once()
    assert thread.send.call_args.kwargs["embed"].description == "chunk two"
    assert result == 999888777


def test_post_report_text_channel_sends_one_embed_per_chunk():
    channel = AsyncMock()
    bot = MagicMock()
    bot.get_channel.return_value = channel

    result = asyncio.run(post_report(123, "Daily report", ["chunk one", "chunk two"], bot))

    assert channel.send.await_count == 2
    titles = [call.kwargs["embed"].title for call in channel.send.await_args_list]
    assert titles == ["Daily report", "Daily report (cont.)"]
    assert result == 123


def test_post_report_never_raises_on_send_failure():
    import discord

    channel = AsyncMock()
    channel.send.side_effect = discord.HTTPException(MagicMock(), "missing access")
    bot = MagicMock()
    bot.get_channel.return_value = channel

    result = asyncio.run(post_report(123, "Daily report", ["chunk"], bot))  # must not raise
    assert result is None
