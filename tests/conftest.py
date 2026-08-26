"""Shared pytest fixtures and configuration."""

import asyncio

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver


class FakeLLM:
    """The surface create_agent and SummarizationMiddleware touch on a model."""

    _llm_type = "fake"

    def bind(self, **kw):
        return self

    def bind_tools(self, tools, **kw):
        return self

    def with_retry(self, **kw):
        return self


class QueueLLM(FakeLLM):
    """Plays back a queue of AIMessages, one per call."""

    def __init__(self, responses):
        self._responses = list(responses)

    async def ainvoke(self, _messages, **kw):
        return self._responses.pop(0)


class FlatLLM(FakeLLM):
    """Answers immediately with ``reply``, never calls a tool."""

    def __init__(self, reply="ok"):
        self._reply = reply

    async def ainvoke(self, _messages, **kw):
        return AIMessage(content=self._reply)


class RecordingLLM(FakeLLM):
    """Answers ``reply`` and records what the model was handed."""

    def __init__(self, seen, reply="ok", flat=False):
        self._seen = seen
        self._reply = reply
        self._flat = flat

    async def ainvoke(self, messages, **kw):
        if self._flat:
            self._seen.extend(str(m.content) for m in messages)
        else:
            self._seen.append([str(m.content) for m in messages])
        return AIMessage(content=self._reply)


class DeadLLM(FakeLLM):
    """Always fails, the way an unreachable endpoint does."""

    async def ainvoke(self, _messages, **kw):
        raise ConnectionError("endpoint down")


class SlowLLM(FakeLLM):
    """Never returns within any reasonable deadline, the way a network hang does."""

    async def ainvoke(self, _messages, **kw):
        await asyncio.sleep(3600)
        raise AssertionError("should have been cancelled by a timeout")


class LoopLLM(FakeLLM):
    """Always asks for ``tool_call`` again, never gives up — drives the budget."""

    def __init__(self, tool_call):
        self._tool_call = tool_call

    async def ainvoke(self, _messages, **kw):
        return AIMessage(content="", tool_calls=[self._tool_call])


def use_fake_llm(monkeypatch, llm):
    """Make every ``provider:model`` string resolve to ``llm``."""
    for module in (
        "agent.agent",
        "langchain.agents.factory",
        "langchain.agents.middleware.summarization",
    ):
        monkeypatch.setattr(f"{module}.init_chat_model", lambda *a, **kw: llm)
    return llm


@pytest.fixture(autouse=True)
def tmp_database(tmp_path, monkeypatch):
    """Point the repository and the conversation checkpointer at a temp file."""
    import agent.watchlist.repository as repo
    from agent import memory
    from agent import agent as agent_mod

    test_path = tmp_path / "agent.db"
    monkeypatch.setattr(repo, "DB_PATH", test_path)
    monkeypatch.setattr(memory, "MEMORY_DB_PATH", tmp_path / "memory.db")
    monkeypatch.setattr(memory, "_CHECKPOINTER", InMemorySaver())
    monkeypatch.setattr(agent_mod, "_AGENT", None)
    return test_path
