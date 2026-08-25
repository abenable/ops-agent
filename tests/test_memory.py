"""Tests for the shared agent memory module."""

import asyncio

from agent import memory
from agent.workflows import investigate
from tests.conftest import FlatLLM, RecordingLLM, use_fake_llm


def test_thread_config_defaults_to_a_fresh_thread():
    a = memory.thread_config()["configurable"]["thread_id"]
    b = memory.thread_config()["configurable"]["thread_id"]
    assert a != b
    assert memory.thread_config("chan-9") == {"configurable": {"thread_id": "chan-9"}}


def test_memory_persists_across_connections(monkeypatch, tmp_database):
    """A thread must outlive the checkpointer connection that wrote it."""
    monkeypatch.setattr(memory, "_CHECKPOINTER", None)
    seen: list[str] = []

    async def scenario():
        try:
            use_fake_llm(monkeypatch, FlatLLM())
            await investigate.investigate("first question", thread_id="durable-thread")
            await memory.close_memory()

            use_fake_llm(monkeypatch, RecordingLLM(seen, flat=True))
            await investigate.investigate("second question", thread_id="durable-thread")
        finally:
            await memory.close_memory()

    asyncio.run(scenario())

    assert "first question" in seen
    assert "second question" in seen
