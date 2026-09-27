"""Tests for streamed investigations and reading conversations back."""

import asyncio
import json

from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from agent import agent as agent_mod
from agent import api
from agent.workflows import conversations, investigate
from tests.conftest import QueueLLM, SlowLLM, use_fake_llm

CALL = {"name": "docker_status", "args": {"container": "api"}, "id": "call-1", "type": "tool_call"}


@tool
def docker_status(container: str) -> str:
    """Return the state of a Docker container (read-only)."""
    return f"{container}: state=exited"


class StreamingLLM(GenericFakeChatModel):
    def bind_tools(self, tools, **kw):
        return self


def _events(question, thread_id=None, **kw):
    async def collect():
        return [e async for e in investigate.stream_investigation(question, thread_id, **kw)]

    return asyncio.run(collect())


def _tool_then_answer(monkeypatch):
    use_fake_llm(monkeypatch, QueueLLM([
        AIMessage(content="", tool_calls=[CALL]),
        AIMessage(content="`api` **exited**."),
    ]))
    monkeypatch.setitem(agent_mod._TOOLS_BY_NAME, "docker_status", docker_status)


def test_stream_reports_the_tool_call_its_result_and_the_answer(monkeypatch):
    _tool_then_answer(monkeypatch)
    events = _events("is the api up?", "t1")
    assert [name for name, _ in events] == ["tool_call", "tool_result", "token", "done"]
    assert events[0][1] == {"id": "call-1", "name": "docker_status", "args": {"container": "api"}}
    assert events[1][1]["content"] == "api: state=exited"
    assert events[2][1]["text"] == "`api` **exited**."
    assert events[3][1] == {"thread_id": "t1"}


def test_streamed_tokens_are_not_repeated_by_the_final_message(monkeypatch):
    use_fake_llm(monkeypatch, StreamingLLM(messages=iter([AIMessage(content="all containers running")])))
    events = _events("status?")
    text = "".join(data["text"] for name, data in events if name == "token")
    assert text == "all containers running"
    assert sum(name == "token" for name, _ in events) > 1


def test_second_turn_does_not_replay_the_first(monkeypatch):
    use_fake_llm(monkeypatch, QueueLLM([AIMessage(content="first"), AIMessage(content="second")]))
    _events("one", "t2")
    events = _events("two", "t2")
    assert [d["text"] for name, d in events if name == "token"] == ["second"]


def test_stream_timeout_ends_with_the_usual_message(monkeypatch):
    monkeypatch.setattr(investigate, "_INVESTIGATION_TIMEOUT", 0.05)
    use_fake_llm(monkeypatch, SlowLLM())
    events = _events("status?")
    assert events[-2] == ("error", {"message": "Investigation timed out after 0s."})
    assert events[-1][0] == "done"


def test_threads_are_listed_and_replayed(monkeypatch):
    _tool_then_answer(monkeypatch)
    _events("is the api up?", "web-1")

    listed = asyncio.run(conversations.list_threads())
    assert [(t["thread_id"], t["title"], t["turns"]) for t in listed] == [("web-1", "is the api up?", 1)]

    messages = asyncio.run(conversations.read_thread("web-1"))
    assert [m["type"] for m in messages] == ["human", "ai", "tool", "ai"]
    assert messages[1]["tool_calls"][0]["name"] == "docker_status"
    assert messages[2]["tool_call_id"] == "call-1"
    assert all(m["at"] for m in messages)
    assert asyncio.run(conversations.read_thread("missing")) is None


def test_api_streams_server_sent_events_and_serves_transcripts(monkeypatch):
    monkeypatch.setattr(api.settings, "api_key", "")
    _tool_then_answer(monkeypatch)
    client = TestClient(api.app)

    with client.stream("POST", "/investigate/stream", json={"question": "is the api up?", "thread_id": "web-2"}) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        frames = [f for f in r.read().decode().split("\n\n") if f]
    names = [f.split("\n")[0].removeprefix("event: ") for f in frames]
    assert names == ["tool_call", "tool_result", "token", "done"]
    assert json.loads(frames[-1].split("data: ", 1)[1]) == {"thread_id": "web-2"}

    assert client.get("/threads").json()["threads"][0]["thread_id"] == "web-2"
    assert len(client.get("/threads/web-2").json()["messages"]) == 4
    assert client.get("/threads/nope").status_code == 404


def _recording_tool(calls):
    @tool
    def docker_status(container: str) -> str:
        """Return the state of a Docker container (read-only)."""
        calls.append(container)
        return f"{container}: state=exited"

    return docker_status


def test_approval_pauses_before_the_tool_and_runs_it_once_approved(monkeypatch):
    calls: list[str] = []
    use_fake_llm(monkeypatch, QueueLLM([
        AIMessage(content="", tool_calls=[CALL]),
        AIMessage(content="`api` **exited**."),
    ]))
    monkeypatch.setitem(agent_mod._TOOLS_BY_NAME, "docker_status", _recording_tool(calls))

    paused = _events("is the api up?", "web-a", approval=True)
    assert [name for name, _ in paused] == ["tool_call", "approval_required", "done"]
    assert [c["id"] for c in paused[1][1]["tool_calls"]] == ["call-1"]
    assert calls == []
    assert asyncio.run(conversations.awaiting_approval("web-a")) == ["call-1"]

    blocked = _events("something else?", "web-a", approval=True)
    assert blocked[0] == ("error", {"message": "Approve or deny the pending tool calls first."})

    resumed = _events(None, "web-a", approval=True, decisions={"call-1": True})
    assert [name for name, _ in resumed] == ["tool_result", "token", "done"]
    assert calls == ["api"]
    assert asyncio.run(conversations.awaiting_approval("web-a")) == []


def test_a_rejected_call_never_runs_and_the_model_is_told(monkeypatch):
    calls: list[str] = []
    use_fake_llm(monkeypatch, QueueLLM([
        AIMessage(content="", tool_calls=[CALL]),
        AIMessage(content="I could not check `api`: the call was denied."),
    ]))
    monkeypatch.setitem(agent_mod._TOOLS_BY_NAME, "docker_status", _recording_tool(calls))

    _events("is the api up?", "web-b", approval=True)
    resumed = _events(None, "web-b", approval=True, decisions={"call-1": False})
    result = dict(resumed)["tool_result"]
    assert result["status"] == "error" and result["content"].startswith("User rejected the tool call")
    assert calls == []
    assert "denied" in dict(resumed)["token"]["text"]


def test_resuming_without_a_paused_run_is_refused(monkeypatch):
    use_fake_llm(monkeypatch, QueueLLM([AIMessage(content="ok")]))
    events = _events(None, "web-c", approval=True, decisions={"x": True})
    assert events[0] == ("error", {"message": "No tool calls are waiting for approval."})


def test_api_lists_tools_and_rejects_unknown_ones(monkeypatch):
    monkeypatch.setattr(api.settings, "api_key", "")
    client = TestClient(api.app)
    names = {t["name"] for t in client.get("/tools").json()["tools"]}
    assert {"docker_status", "docker_logs", "list_services"} <= names
    bad = client.post("/investigate/stream", json={"question": "q", "tools": ["rm_rf"]})
    assert bad.status_code == 422 and "rm_rf" in bad.json()["detail"]
    assert client.post("/investigate/stream", json={"thread_id": "t"}).status_code == 422


def test_stream_can_ask_the_incident_report_question(monkeypatch):
    monkeypatch.setattr(api.settings, "api_key", "")
    use_fake_llm(monkeypatch, QueueLLM([AIMessage(content="**Summary** healthy.")]))
    client = TestClient(api.app)
    with client.stream("POST", "/investigate/stream", json={"report": "api", "thread_id": "web-r"}) as r:
        r.read()
    question = client.get("/threads/web-r").json()["messages"][0]["content"]
    assert question.startswith("Write a structured incident report for the service `api`.")
    both = client.post("/investigate/stream", json={"report": "api", "question": "q"})
    assert both.status_code == 422


def test_stream_rejects_unknown_fields_rather_than_ignoring_them(monkeypatch):
    monkeypatch.setattr(api.settings, "api_key", "")
    client = TestClient(api.app)
    assert client.post("/investigate/stream", json={"question": "q", "aproval": True}).status_code == 422
