"""Tests for the instrumented eval loop the eval/*.ipynb notebooks share."""

import asyncio
import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

import eval_transcript as et

from agent.config.settings import settings


@tool
def ping(x: str) -> str:
    """Echo x back."""
    _RAN.append(x)
    return f"pong:{x}"


_RAN: list[str] = []


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Transcripts land in tmp_path, never in the repo's eval/logs/."""
    _RAN.clear()
    monkeypatch.setattr(et, "TRANSCRIPT_DIR", tmp_path)
    return tmp_path


def _fake_model(monkeypatch, responses):
    """Make init_chat_model return a model replaying `responses`."""

    class _LLM:
        def bind_tools(self, *a, **kw):
            return self

        async def ainvoke(self, _messages, **kw):
            nxt = responses.pop(0)
            if isinstance(nxt, Exception):
                raise nxt
            return nxt

    monkeypatch.setattr(et, "init_chat_model", lambda *a, **kw: _LLM())


def _tool_calls(n, start=0):
    return AIMessage(
        content="",
        tool_calls=[
            {"name": "ping", "args": {"x": f"c{start + i}"}, "id": f"id{start + i}"}
            for i in range(n)
        ],
    )


def _latest(tmp_path) -> dict:
    return json.loads(sorted(tmp_path.glob("*.json"))[-1].read_text())


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
    ) == {"role": "ai", "content": "pong", "tool_calls": [{"name": "f", "args": {"x": 1}}]}


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


def test_grade_reports_the_substrings_an_answer_missed():
    assert et._grade("anything", None) is None
    assert et._grade("Errors from NODE-EXPORTER, 20 of 1703", ["node-exporter", "1703"])["passed"]
    failed = et._grade("loki is unhappy", ["node-exporter", "sample"])
    assert failed["passed"] is False
    assert failed["missing"] == ["node-exporter", "sample"]


def test_budget_counts_tool_calls_not_turns(monkeypatch, isolated):
    """The budget counts tool calls, not model turns."""
    monkeypatch.setattr(settings, "max_tool_steps", 4)
    _fake_model(monkeypatch, [_tool_calls(3), _tool_calls(3), AIMessage(content="summary")])

    answer = asyncio.run(et.run_eval_loop("t:budget", [ping], "sys", "q"))

    assert len(_RAN) == 4
    assert answer == "summary"


def test_a_crashed_run_still_writes_its_transcript(monkeypatch, isolated):
    """The runs worth reading are the ones that died; the dump is in a finally."""
    _fake_model(monkeypatch, [RuntimeError("endpoint down")])

    with pytest.raises(RuntimeError):
        asyncio.run(et.run_eval_loop("t:crash", [ping], "sys", "q"))

    dumped = _latest(isolated)
    assert dumped["error"] == "RuntimeError: endpoint down"
    assert dumped["grade"] is None


def test_unknown_tool_is_reported_as_missing_not_as_a_failure(monkeypatch, isolated):
    """An invented tool name must not read as a broken tool."""
    monkeypatch.setattr(settings, "max_tool_steps", 10)
    _fake_model(monkeypatch, [
        AIMessage(content="", tool_calls=[{"name": "nope", "args": {}, "id": "id0"}]),
        AIMessage(content="done"),
    ])

    asyncio.run(et.run_eval_loop("t:unknown", [ping], "sys", "q"))

    dumped = _latest(isolated)
    result = dumped["calls"][0]["tool_results"][0]["result"]
    assert "no tool named 'nope'" in result
    assert "failed" not in result
    assert dumped["tool_calls"] == 0
    assert dumped["tool_calls_requested"] == 1


def test_repeats_grade_through_the_shared_grader(monkeypatch, isolated):
    _fake_model(monkeypatch, [AIMessage(content="node-exporter is down")] * 2)

    summary = asyncio.run(
        et.run_eval_repeats("t:repeats", [ping], "sys", "q", ["node-exporter"], runs=2)
    )

    assert summary["runs"] == 2
    assert summary["graded"] == 2
    assert summary["passed"] == 2
    assert summary["pass_rate"] == 1.0
    assert summary["distinct_answers"] == 1
    assert _latest(isolated)["grade"]["passed"]


def test_grader_accepts_alternatives_and_grades_tool_use():
    """Any-of wording, required tools, and forbidden tools all gate the verdict."""
    refusal = et._grade("I cannot check that", [et.REFUSAL], ["list_services"], ["list_services"])
    assert refusal["passed"]

    fabricated = et._grade("It is healthy", [et.REFUSAL], ["list_services"], ["list_services"])
    assert not fabricated["passed"] and fabricated["missing"]

    # an any-of tool entry passes on either alternative
    either = et._grade("x", None, ["get_label_values"], [("list_metric_names", "get_label_values")])
    assert either["passed"]

    never_queried = et._grade("x", None, ["get_label_values"], ["query_prometheus"])
    assert not never_queried["passed"]
    assert never_queried["missing_tools"] == ["query_prometheus"]

    used_forbidden = et._grade("x", None, ["docker_status"], None, ["docker_status"])
    assert not used_forbidden["passed"]
    assert used_forbidden["forbidden_used"] == ["docker_status"]

    assert et._grade("x", None, [], None, None) is None
