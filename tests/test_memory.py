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


def test_thread_config_defaults_to_a_fresh_thread():
    a = memory.thread_config()["configurable"]["thread_id"]
    b = memory.thread_config()["configurable"]["thread_id"]
    assert a != b
    assert memory.thread_config("chan-9", llm="x")["configurable"] == {
        "thread_id": "chan-9",
        "llm": "x",
    }
