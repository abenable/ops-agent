"""Tests for the agentic investigation loop."""

import asyncio

from langchain_core.messages import AIMessage

from agent import investigate


class _FakeLLM:
    """Plays back a queue of AIMessages; bind_tools returns self."""

    def __init__(self, responses):
        self._responses = list(responses)

    def bind_tools(self, _tools):
        return self

    async def ainvoke(self, _messages):
        return self._responses.pop(0)


class _FakeTool:
    def __init__(self, output):
        self.output = output
        self.calls = []

    async def ainvoke(self, args):
        self.calls.append(args)
        return self.output


def _tool_call(name="docker_status", args=None, call_id="call-1"):
    return {"name": name, "args": args or {"container": "api"}, "id": call_id}


def test_loop_executes_tool_then_answers(monkeypatch):
    responses = [
        AIMessage(content="", tool_calls=[_tool_call()]),
        AIMessage(content="Container is **running**."),
    ]
    monkeypatch.setattr(investigate, "get_llm", lambda **kw: _FakeLLM(responses))
    tool = _FakeTool("api: state=running")
    monkeypatch.setitem(investigate._TOOLS_BY_NAME, "docker_status", tool)

    out = asyncio.run(investigate.investigate("is the api up?"))

    assert tool.calls == [{"container": "api"}]
    assert "running" in out


def test_loop_answers_without_tools(monkeypatch):
    responses = [AIMessage(content="Nothing is wrong.")]
    monkeypatch.setattr(investigate, "get_llm", lambda **kw: _FakeLLM(responses))
    out = asyncio.run(investigate.investigate("all good?"))
    assert out == "Nothing is wrong."


def test_tool_error_is_fed_back_not_raised(monkeypatch):
    responses = [
        AIMessage(content="", tool_calls=[_tool_call()]),
        AIMessage(content="Docker is unreachable."),
    ]
    monkeypatch.setattr(investigate, "get_llm", lambda **kw: _FakeLLM(responses))

    class _BoomTool:
        async def ainvoke(self, _args):
            raise RuntimeError("socket missing")

    monkeypatch.setitem(investigate._TOOLS_BY_NAME, "docker_status", _BoomTool())
    out = asyncio.run(investigate.investigate("is the api up?"))
    assert "unreachable" in out


def test_step_cap_triggers_final_summary(monkeypatch):
    monkeypatch.setattr(investigate.settings, "max_tool_steps", 2)
    responses = [
        AIMessage(content="", tool_calls=[_tool_call(call_id="c1")]),
        AIMessage(content="", tool_calls=[_tool_call(call_id="c2")]),
        AIMessage(content="Summary after cap."),
    ]
    fake = _FakeLLM(responses)  # one instance: the loop and the fallback share the queue
    monkeypatch.setattr(investigate, "get_llm", lambda **kw: fake)
    monkeypatch.setitem(investigate._TOOLS_BY_NAME, "docker_status", _FakeTool("ok"))

    out = asyncio.run(investigate.investigate("why is it slow?"))
    assert out == "Summary after cap."


def test_llm_failure_returns_error_message(monkeypatch):
    class _DeadLLM:
        def bind_tools(self, _tools):
            return self

        async def ainvoke(self, _messages):
            raise ConnectionError("endpoint down")

    monkeypatch.setattr(investigate, "get_llm", lambda **kw: _DeadLLM())
    out = asyncio.run(investigate.investigate("status?"))
    assert out.startswith("Investigation failed:")


def test_report_uses_incident_template(monkeypatch):
    seen = []

    class _RecordingLLM:
        def bind_tools(self, _tools):
            return self

        async def ainvoke(self, messages):
            seen.extend(str(m.content) for m in messages)
            return AIMessage(content="**Summary** all healthy.")

    monkeypatch.setattr(investigate, "get_llm", lambda **kw: _RecordingLLM())
    out = asyncio.run(investigate.report("marconi-agent-api"))
    assert "healthy" in out
    assert any("incident report" in s and "marconi-agent-api" in s for s in seen)
