"""Tests for the eval transcript instrumentation the eval/*.ipynb notebooks share."""

import asyncio
import json

import pytest

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

import eval_transcript as et

from agent import agent as agent_mod
from agent.tools import configured_tools
from tests.conftest import DeadLLM, QueueLLM, use_fake_llm


def _tool_call(name="docker_status", args=None, call_id="call-1"):
    return {"name": name, "args": args or {"container": "api"}, "id": call_id, "type": "tool_call"}


def _make_status_tool(output, calls):
    @tool
    def docker_status(container: str) -> str:
        """Return the state of a Docker container (read-only)."""
        calls.append({"container": container})
        return output

    return docker_status


def _latest(tmp_path) -> dict:
    return json.loads(sorted(tmp_path.rglob("*.json"))[-1].read_text())


def test_text_coerces_content_blocks():
    assert et._text("  hi  ") == "hi"
    assert et._text([{"type": "thinking", "thinking": "..."}, {"type": "text", "text": "pong"}]) == "pong"


def test_serialize_message_covers_every_role():
    assert et._serialize_message(SystemMessage(content="sys")) == {"role": "system", "content": "sys"}
    assert et._serialize_message(HumanMessage(content="hi")) == {"role": "human", "content": "hi"}
    assert et._serialize_message(ToolMessage(content="result", tool_call_id="abc")) == {
        "role": "tool",
        "tool_call_id": "abc",
        "content": "result",
    }
    assert et._serialize_message(
        AIMessage(content="pong", tool_calls=[{"name": "f", "args": {"x": 1}, "id": "1"}])
    ) == {
        "role": "ai",
        "content": "pong",
        "tool_calls": [{"id": "1", "name": "f", "args": {"x": 1}}],
        "finish_reason": None,
    }


def test_usage_totals_default_to_zero_when_unreported():
    reported = AIMessage(
        content="pong", usage_metadata={"input_tokens": 3, "output_tokens": 1, "total_tokens": 4}
    )
    assert et._usage(reported) == {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4}
    assert et._usage(AIMessage(content="pong")) == {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    }


def test_reasoning_output_is_kept_when_text_extraction_finds_nothing():
    """A reasoning model's tokens must not be counted and then thrown away.

    _text() keeps only blocks carrying a "text" key, so a run that produced
    32k reasoning tokens serialised to "" and the content was unrecoverable.
    """
    blocks = [{"type": "reasoning", "reasoning": "thinking hard about loki"}]
    out = et._serialize_message(AIMessage(content=blocks))
    assert out["content"] == ""
    assert out["raw_content"] == blocks

    carried = et._serialize_message(
        AIMessage(content="", additional_kwargs={"reasoning_content": "step 1..."})
    )
    assert carried["reasoning_content"] == "step 1..."

    # a normal answer keeps nothing extra
    plain = et._serialize_message(AIMessage(content="done"))
    assert "raw_content" not in plain and "reasoning_content" not in plain


def test_finish_reason_is_recorded():
    truncated = et._serialize_message(
        AIMessage(content="", response_metadata={"finish_reason": "length"})
    )
    assert truncated["finish_reason"] == "length"


def test_run_agent_eval_drives_the_real_agent_and_dumps_a_transcript(monkeypatch, tmp_path):
    """run_agent_eval goes through get_agent(), not a hand-rolled loop."""
    monkeypatch.setattr(et, "TRANSCRIPT_DIR", tmp_path)
    use_fake_llm(monkeypatch, QueueLLM([
        AIMessage(content="", tool_calls=[_tool_call()]),
        AIMessage(content="Container is **running**."),
    ]))
    calls = []
    monkeypatch.setitem(
        agent_mod._TOOLS_BY_NAME, "docker_status", _make_status_tool("api: state=running", calls)
    )

    answer = asyncio.run(
        et.run_agent_eval("t:inscope", "is the api up?", thread_id="t-inscope", tools=["docker_status"])
    )

    assert calls == [{"container": "api"}]
    assert "running" in answer

    dumped = _latest(tmp_path)
    assert dumped["label"] == "t:inscope"
    assert dumped["tools"] == ["docker_status"]
    assert dumped["tool_calls"] == 1
    assert dumped["tool_names"] == ["docker_status"]


def test_run_agent_eval_defaults_tools_to_the_configured_set(monkeypatch, tmp_path):
    """With no `tools`, the transcript records the same set the Discord bot binds."""
    monkeypatch.setattr(et, "TRANSCRIPT_DIR", tmp_path)
    use_fake_llm(monkeypatch, QueueLLM([AIMessage(content="ok")]))

    asyncio.run(et.run_agent_eval("t:default-tools", "q", thread_id="t-default"))

    dumped = _latest(tmp_path)
    assert dumped["tools"] == [t.name for t in configured_tools()]


def test_run_agent_eval_measures_only_the_new_turn(monkeypatch, tmp_path):
    """A follow-up on the same thread reports its own cost, not the whole thread's."""
    monkeypatch.setattr(et, "TRANSCRIPT_DIR", tmp_path)
    use_fake_llm(monkeypatch, QueueLLM([
        AIMessage(
            content="first answer",
            usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
        ),
        AIMessage(
            content="second answer",
            usage_metadata={"input_tokens": 30, "output_tokens": 4, "total_tokens": 34},
        ),
    ]))

    asyncio.run(et.run_agent_eval("t:first", "q1", thread_id="shared-thread"))
    asyncio.run(et.run_agent_eval("t:second", "q2", thread_id="shared-thread", resume=True))

    dumped = _latest(tmp_path)
    assert dumped["answer"] == "second answer"
    assert dumped["new_messages"] == 2  # this turn's Human + AI only, not q1's
    assert dumped["total_usage"]["total_tokens"] == 34


def test_an_exhausted_model_is_recorded_as_an_error(monkeypatch, tmp_path):
    """ModelRetryMiddleware returns a message instead of raising."""
    monkeypatch.setattr(et, "TRANSCRIPT_DIR", tmp_path)
    use_fake_llm(monkeypatch, DeadLLM())

    asyncio.run(et.run_agent_eval("t:dead", "q", thread_id="t-dead"))

    dumped = _latest(tmp_path)
    assert dumped["error"].startswith("Model call failed")


def test_a_crashed_run_still_leaves_a_transcript(monkeypatch, tmp_path):
    """A run that dies mid-invoke is still recorded."""
    monkeypatch.setattr(et, "TRANSCRIPT_DIR", tmp_path)

    class Exploding:
        async def ainvoke(self, *a, **kw):
            raise ConnectionError("endpoint down")

    async def _get_agent(tools=None):
        return Exploding()

    monkeypatch.setattr(agent_mod, "get_agent", _get_agent)

    with pytest.raises(ConnectionError):
        asyncio.run(et.run_agent_eval("t:boom", "q", thread_id="t-boom"))

    dumped = _latest(tmp_path)
    assert dumped["label"] == "t:boom"
    assert "endpoint down" in dumped["error"]
    assert dumped["answer"] == ""
    assert dumped["total_usage"]["total_tokens"] == 0


def test_a_fresh_thread_is_measured_from_zero(monkeypatch, tmp_path):
    """Same thread_id with resume=False is a new conversation, measured from zero."""
    monkeypatch.setattr(et, "TRANSCRIPT_DIR", tmp_path)
    use_fake_llm(monkeypatch, QueueLLM([
        AIMessage(content="first", usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}),
        AIMessage(content="second", usage_metadata={"input_tokens": 30, "output_tokens": 4, "total_tokens": 34}),
    ]))

    asyncio.run(et.run_agent_eval("t:one", "q1", thread_id="reused-id"))
    asyncio.run(et.run_agent_eval("t:two", "q2", thread_id="reused-id"))

    dumped = _latest(tmp_path)
    assert dumped["answer"] == "second"
    assert dumped["new_messages"] == 2
    assert dumped["total_usage"]["total_tokens"] == 34
