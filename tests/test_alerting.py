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
