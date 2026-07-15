"""Tests for incident and reporting workflows."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.storage.repository import list_incidents
import agent.workflows.incident as incident_module
from agent.tools import query_tools
from agent.workflows.incident import (
    llm_supports_tool_calls,
    run_agentic_investigation,
    run_ask_workflow,
    run_incident_workflow,
)


class FakeMessage:
    def __init__(self, content: str = "", tool_calls: list | None = None):
        self.content = content
        self.tool_calls = tool_calls or []


class FakeLLM:
    def __init__(self, responses: list | None = None):
        self._responses = responses or [FakeMessage("fake incident summary")]
        self._index = 0

    def bind_tools(self, _tools):
        return self

    async def ainvoke(self, _messages):
        resp = self._responses[self._index]
        self._index += 1
        return resp


class RaisingLLM:
    def bind_tools(self, _tools):
        return self

    async def ainvoke(self, _messages):
        raise RuntimeError("LLM unreachable")


def test_incident_workflow(tmp_database):
    with patch("agent.workflows.incident.get_llm", return_value=FakeLLM()):
        result = asyncio.run(run_incident_workflow("web"))

    assert isinstance(result, dict)
    assert "incident_id" in result
    assert result["summary"] == "fake incident summary"

    rows = list_incidents()
    assert any(
        row["service"] == "web" and row["summary"] == result["summary"]
        for row in rows
    )


@pytest.fixture
def patched_tool_sources(monkeypatch):
    """Patch Prometheus/Loki backing calls so agentic tests don't hit the network."""
    prom = AsyncMock(return_value={"data": {"result": [{"value": 1}]}})
    prom_range = AsyncMock(return_value={"data": {"result": [{"values": [[1, 2]]}]}})
    names = AsyncMock(return_value=["up", "http_requests_total"])
    labels = AsyncMock(return_value=["web", "api"])
    loki_q = AsyncMock(return_value={"data": {"result": [{"line": "log"}]}})

    monkeypatch.setattr(query_tools.prometheus, "query_prometheus", prom)
    monkeypatch.setattr(query_tools.prometheus, "query_prometheus_range", prom_range)
    monkeypatch.setattr(query_tools.prometheus, "list_metric_names", names)
    monkeypatch.setattr(query_tools.prometheus, "get_label_values", labels)
    monkeypatch.setattr(query_tools.loki, "query_loki", loki_q)

    return {
        "query_prometheus": prom,
        "query_prometheus_range": prom_range,
        "list_metric_names": names,
        "get_label_values": labels,
        "query_loki": loki_q,
    }


def test_agentic_loop_runs_tool_and_returns_summary(tmp_database, patched_tool_sources, monkeypatch):
    monkeypatch.setattr(incident_module.settings, "max_tool_steps", 6)

    responses = [
        FakeMessage(
            content="",
            tool_calls=[
                {
                    "name": "query_prometheus",
                    "args": {"promql": "up == 0"},
                    "id": "call-1",
                }
            ],
        ),
        FakeMessage(content="agentic summary"),
    ]

    with patch("agent.workflows.incident.get_llm", return_value=FakeLLM(responses)):
        result = asyncio.run(run_incident_workflow("web"))

    assert result["summary"] == "agentic summary"
    patched_tool_sources["query_prometheus"].assert_awaited_once_with("up == 0")


def test_agentic_loop_terminates_at_max_tool_steps(tmp_database, patched_tool_sources, monkeypatch):
    from agent.config.settings import Settings

    monkeypatch.setattr(incident_module, "settings", Settings(max_tool_steps=2))

    # Avoid extra Prometheus hits from the static fallback; we only want to count tool calls.
    monkeypatch.setattr(incident_module, "get_service_metrics", AsyncMock(return_value={"service": "web"}))
    monkeypatch.setattr(incident_module, "get_recent_logs", AsyncMock(return_value="logs"))
    monkeypatch.setattr(incident_module, "get_service_status", AsyncMock(return_value={"status": "ok"}))

    always_tool = FakeMessage(
        content="",
        tool_calls=[
            {
                "name": "query_prometheus",
                "args": {"promql": "up == 0"},
                "id": "call-1",
            }
        ],
    )

    responses = [always_tool, always_tool, FakeMessage("max-steps fallback summary")]
    with patch("agent.workflows.incident.get_llm", return_value=FakeLLM(responses)):
        result = asyncio.run(run_incident_workflow("web"))

    # It should hit the tool exactly twice (max steps), then fall back.
    assert patched_tool_sources["query_prometheus"].await_count == 2
    assert result["summary"] == "max-steps fallback summary"


def test_incident_workflow_falls_back_when_llm_fails(tmp_database):
    with patch(
        "agent.workflows.incident.get_llm",
        side_effect=[RaisingLLM(), FakeLLM([FakeMessage("fallback summary")])],
    ):
        result = asyncio.run(run_incident_workflow("web"))

    assert "fallback summary" in result["summary"]


def test_ask_workflow_does_not_store_incident(tmp_database, patched_tool_sources, monkeypatch):
    monkeypatch.setattr(incident_module.settings, "max_tool_steps", 6)

    responses = [
        FakeMessage(
            content="",
            tool_calls=[
                {"name": "list_metric_names", "args": {"match": "cpu"}, "id": "call-1"}
            ],
        ),
        FakeMessage(content="ask answer"),
    ]

    before = len(list_incidents())
    with patch("agent.workflows.incident.get_llm", return_value=FakeLLM(responses)):
        answer = asyncio.run(run_ask_workflow("what metrics exist?"))

    assert answer == "ask answer"
    assert len(list_incidents()) == before


def test_llm_supports_tool_calls_probe(tmp_database):
    with patch(
        "agent.workflows.incident.get_llm",
        return_value=FakeLLM([FakeMessage("", tool_calls=[{"name": "query_prometheus"}])]),
    ):
        assert asyncio.run(llm_supports_tool_calls()) is True

    with patch(
        "agent.workflows.incident.get_llm",
        return_value=FakeLLM([FakeMessage("no tools here")]),
    ):
        assert asyncio.run(llm_supports_tool_calls()) is False

    with patch("agent.workflows.incident.get_llm", return_value=RaisingLLM()):
        assert asyncio.run(llm_supports_tool_calls()) is False
