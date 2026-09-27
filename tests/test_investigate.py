"""Tests for the agentic investigation loop (official create_agent harness)."""

import asyncio

from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from agent import agent as agent_mod
from agent.config.settings import settings
from agent.workflows import investigate
from agent.workflows.report import report
from tests.conftest import DeadLLM, LoopLLM, QueueLLM, RecordingLLM, SlowLLM, use_fake_llm


def _tool_call(name="docker_status", args=None, call_id="call-1"):
    return {
        "name": name,
        "args": args or {"container": "api"},
        "id": call_id,
        "type": "tool_call",
    }


def _make_status_tool(output, calls):
    @tool
    def docker_status(container: str) -> str:
        """Return the state of a Docker container (read-only)."""
        calls.append({"container": container})
        return output

    return docker_status


def _make_boom_tool():
    @tool
    def docker_status(container: str) -> str:
        """Return the state of a Docker container (read-only)."""
        raise RuntimeError("socket missing")

    return docker_status


def test_loop_executes_tool_then_answers(monkeypatch):
    use_fake_llm(monkeypatch, QueueLLM([
        AIMessage(content="", tool_calls=[_tool_call()]),
        AIMessage(content="Container is **running**."),
    ]))
    calls = []
    monkeypatch.setitem(
        agent_mod._TOOLS_BY_NAME, "docker_status", _make_status_tool("api: state=running", calls)
    )

    out = asyncio.run(investigate.investigate("is the api up?"))

    assert calls == [{"container": "api"}]
    assert "running" in out


def test_loop_answers_without_tools(monkeypatch):
    use_fake_llm(monkeypatch, QueueLLM([AIMessage(content="Nothing is wrong.")]))
    assert asyncio.run(investigate.investigate("all good?")) == "Nothing is wrong."


def test_tool_error_is_fed_back_not_raised(monkeypatch):
    use_fake_llm(monkeypatch, QueueLLM([
        AIMessage(content="", tool_calls=[_tool_call()]),
        AIMessage(content="Docker is unreachable."),
    ]))
    monkeypatch.setitem(agent_mod._TOOLS_BY_NAME, "docker_status", _make_boom_tool())

    out = asyncio.run(investigate.investigate("is the api up?"))
    assert "unreachable" in out


def test_tool_limit_stops_the_loop(monkeypatch):
    monkeypatch.setattr(settings, "max_tool_steps", 2)
    use_fake_llm(monkeypatch, LoopLLM(_tool_call()))
    calls = []
    monkeypatch.setitem(agent_mod._TOOLS_BY_NAME, "docker_status", _make_status_tool("ok", calls))

    out = asyncio.run(investigate.investigate("why is it slow?"))

    assert len(calls) == 2
    assert "limit" in out.lower()


def test_llm_failure_returns_error_message(monkeypatch):
    """ModelRetryMiddleware exhausts its retries and returns an AIMessage, not a raise."""
    use_fake_llm(monkeypatch, DeadLLM())
    assert "Model call failed" in asyncio.run(investigate.investigate("status?"))


def test_llm_hang_times_out(monkeypatch):
    """A hang (no exception raised) is still bounded by the outer wait_for ceiling."""
    monkeypatch.setattr(investigate, "_INVESTIGATION_TIMEOUT", 0.05)
    use_fake_llm(monkeypatch, SlowLLM())
    assert asyncio.run(investigate.investigate("status?")) == "Investigation timed out after 0s."


def test_report_uses_incident_template(monkeypatch):
    seen = []
    use_fake_llm(monkeypatch, RecordingLLM(seen, reply="**Summary** all healthy.", flat=True))

    out = asyncio.run(report("marconi-agent-api"))

    assert "healthy" in out
    assert any("incident report" in s and "marconi-agent-api" in s for s in seen)


def test_thread_id_keeps_history_and_isolates_threads(monkeypatch):
    """Same thread_id sees the earlier turn; a different one starts clean."""
    seen: list = []
    use_fake_llm(monkeypatch, RecordingLLM(seen))

    asyncio.run(investigate.investigate("first question", thread_id="chan-1"))
    asyncio.run(investigate.investigate("second question", thread_id="chan-1"))
    asyncio.run(investigate.investigate("other channel", thread_id="chan-2"))

    assert seen[0][1:] == ["first question"]
    assert "first question" in seen[1]
    assert "first question" not in seen[2]


def test_text_keeps_plain_string_blocks_next_to_thinking():
    """Regression: Gemma with thinking returns [thinking dict, answer str]; the str was dropped."""
    content = [{"type": "thinking", "thinking": "hidden", "index": 0}, "`api` exited."]
    assert investigate._text(content) == "`api` exited."
