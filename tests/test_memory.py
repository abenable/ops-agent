"""Tests for the shared agent memory module."""

import asyncio

from langchain_core.messages import AIMessage

from agent import engine, memory
from agent.workflows import investigate


class _FlatLLM:
    """Answers immediately, no tool calls."""

    def bind_tools(self, _tools):
        return self

    async def ainvoke(self, _messages):
        return AIMessage(content="ok")


def test_history_and_forget_roundtrip(monkeypatch):
    monkeypatch.setattr(engine, "get_llm", lambda **kw: _FlatLLM())

    async def scenario():
        assert await memory.history("thread-a") == []
        await investigate.investigate("first question", thread_id="thread-a")
        remembered = [m.content for m in await memory.history("thread-a")]
        assert remembered == ["first question", "ok"]
        await memory.forget("thread-a")
        return await memory.history("thread-a")

    assert asyncio.run(scenario()) == []


def test_seed_preloads_a_thread_before_the_first_real_turn(monkeypatch):
    monkeypatch.setattr(engine, "get_llm", lambda **kw: _FlatLLM())

    async def scenario():
        await engine.seed("report-thread", "here is today's report")
        await investigate.investigate("explain", thread_id="report-thread")
        return [m.content for m in await memory.history("report-thread")]

    assert asyncio.run(scenario()) == ["here is today's report", "explain", "ok"]


def test_seeded_content_actually_reaches_the_model(monkeypatch):
    """The seed must survive agent.memory.window() trimming, not just land in
    the raw checkpoint — a lone leading AIMessage gets silently dropped by
    window()'s start_on="human", so this must be visible in what the model
    is actually sent, not only in memory.history()."""
    seen: list[list[str]] = []

    class _RecordingLLM:
        def bind_tools(self, _tools):
            return self

        async def ainvoke(self, messages):
            seen.append([str(m.content) for m in messages])
            return AIMessage(content="ok")

    monkeypatch.setattr(engine, "get_llm", lambda **kw: _RecordingLLM())

    async def scenario():
        await engine.seed("seeded-thread", "here is today's report")
        await investigate.investigate("explain", thread_id="seeded-thread")

    asyncio.run(scenario())

    assert "here is today's report" in seen[0]


def test_thread_config_defaults_to_a_fresh_thread():
    a = memory.thread_config()["configurable"]["thread_id"]
    b = memory.thread_config()["configurable"]["thread_id"]
    assert a != b
    assert memory.thread_config("chan-9", llm="x")["configurable"] == {
        "thread_id": "chan-9",
        "llm": "x",
    }
