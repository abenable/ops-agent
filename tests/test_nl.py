"""Tests for the natural-language (DM/@mention) workflow.

Regression coverage for the bug where an exception in this path was
swallowed by discord.py and never reached the user or the log channel.
"""

import asyncio
import contextlib

from agent.workflows import nl


class _FakeChannel:
    id = 999

    def __init__(self):
        self.sent = []

    @contextlib.asynccontextmanager
    async def typing(self):
        yield

    async def send(self, msg):
        self.sent.append(msg)


class _FakeUser:
    bot = False


class _FakeMessage:
    def __init__(self, content, guild=None, mentions=None):
        self.content = content
        self.guild = guild
        self.author = _FakeUser()
        self.mentions = mentions or []
        self.channel = _FakeChannel()
        self.replies = []

    async def reply(self, msg):
        self.replies.append(msg)


class _FakeBot:
    def __init__(self):
        self.user = object()


def test_dm_answers_through_investigate(monkeypatch):
    async def fake_investigate(question, thread_id=None):
        assert thread_id == "999"
        return f"answer: {question}"

    monkeypatch.setattr(nl.investigator, "investigate", fake_investigate)
    bot = _FakeBot()
    message = _FakeMessage("why is loki down?")  # guild=None -> DM

    asyncio.run(nl.handle_message(bot, message))

    assert message.replies == ["answer: why is loki down?"]


def test_mention_strips_the_mention_text(monkeypatch):
    seen = {}

    async def fake_investigate(question, thread_id=None):
        seen["question"] = question
        return "ok"

    monkeypatch.setattr(nl.investigator, "investigate", fake_investigate)
    bot = _FakeBot()
    message = _FakeMessage("<@123> check prometheus", guild=object(), mentions=[bot.user])

    asyncio.run(nl.handle_message(bot, message))

    assert seen["question"] == "check prometheus"


def test_empty_question_prompts_instead_of_calling_investigate(monkeypatch):
    async def fail(*_a, **_kw):
        raise AssertionError("should not be called")

    monkeypatch.setattr(nl.investigator, "investigate", fail)
    bot = _FakeBot()
    message = _FakeMessage("<@123>", guild=object(), mentions=[bot.user])

    asyncio.run(nl.handle_message(bot, message))

    assert "What should I look into" in message.replies[0]


def test_guild_message_without_mention_is_ignored(monkeypatch):
    async def fail(*_a, **_kw):
        raise AssertionError("should not be called")

    monkeypatch.setattr(nl.investigator, "investigate", fail)
    bot = _FakeBot()
    message = _FakeMessage("just chatting", guild=object())

    asyncio.run(nl.handle_message(bot, message))

    assert message.replies == []


def test_failure_replies_with_an_error_instead_of_going_silent(monkeypatch):
    async def boom(*_a, **_kw):
        raise RuntimeError("llm endpoint unreachable")

    monkeypatch.setattr(nl.investigator, "investigate", boom)
    bot = _FakeBot()
    message = _FakeMessage("why is loki down?")

    asyncio.run(nl.handle_message(bot, message))

    assert message.replies, "a failure must still produce a reply, not silence"
    assert "llm endpoint unreachable" in message.replies[0]
