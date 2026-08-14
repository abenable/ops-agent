"""Tests for the shared agentic investigation workflow."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import agent.workflows.incident as incident_module
from agent.helpers import query_tools
from agent.workflows.incident import (
    llm_supports_tool_calls,
    run_agentic_investigation,
    run_ask_workflow,
    run_scoped_investigation,
    _parse_dsml_calls,
    _strip_dsml,
)


class FakeMessage:
    def __init__(self, content: str = "", tool_calls: list | None = None):
        self.content = content
        self.tool_calls = tool_calls or []


class FakeLLM:
    def __init__(self, responses: list | None = None):
        self._responses = responses or [FakeMessage("fake incident summary")]
        self._index = 0

    def bind_tools(self, _tools, **kwargs):
        return self

    async def ainvoke(self, _messages):
        resp = self._responses[self._index]
        self._index += 1
        return resp


class RaisingLLM:
    def bind_tools(self, _tools, **kwargs):
        return self

    async def ainvoke(self, _messages):
        raise RuntimeError("LLM unreachable")


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
        result = asyncio.run(run_ask_workflow("investigate web"))

    assert result == "agentic summary"
    patched_tool_sources["query_prometheus"].assert_awaited_once_with("up == 0")


def test_agentic_loop_terminates_at_max_tool_steps(tmp_database, patched_tool_sources, monkeypatch):
    from agent.config.settings import Settings

    monkeypatch.setattr(incident_module, "settings", Settings(max_tool_steps=2, _env_file=None))

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
        result = asyncio.run(run_ask_workflow("investigate web"))

    # It should hit the tool exactly twice (max steps), then fall back.
    assert patched_tool_sources["query_prometheus"].await_count == 2
    assert result == "max-steps fallback summary"


def test_ask_workflow_uses_general_prompt(tmp_database, patched_tool_sources, monkeypatch):
    """/ask must NOT use the incident ranked-hypothesis prompt."""
    captured = {}
    original = run_agentic_investigation

    async def spy(prompt, *, system_prompt=incident_module.SYSTEM_PROMPT, tools=None, history=None, kind="ask"):
        captured["system_prompt"] = system_prompt
        return "ask answer"

    monkeypatch.setattr(incident_module, "run_agentic_investigation", spy)
    asyncio.run(run_ask_workflow("what metrics exist?"))
    assert captured["system_prompt"] is incident_module.SYSTEM_PROMPT


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


def test_scoped_investigation_returns_summary_and_raw(tmp_database, patched_tool_sources, monkeypatch):
    """/metrics //logs run the agentic loop and return (summary, concatenated raw tool output)."""
    monkeypatch.setattr(incident_module.settings, "max_tool_steps", 6)

    responses = [
        FakeMessage(
            content="",
            tool_calls=[
                {"name": "query_prometheus", "args": {"promql": "up{job='n8n'}"}, "id": "call-1"}
            ],
        ),
        FakeMessage(content="n8n is up with 9 containers reporting."),
    ]

    with patch("agent.workflows.incident.get_llm", return_value=FakeLLM(responses)):
        summary, raw = asyncio.run(run_scoped_investigation("metrics for n8n"))

    assert summary == "n8n is up with 9 containers reporting."
    assert "query_prometheus" in raw
    patched_tool_sources["query_prometheus"].assert_awaited_once_with("up{job='n8n'}")


def test_parse_dsml_calls_extracts_inline_tool_calls():
    # DeepSeek emits tool calls inline as <｜｜DSML｜｜> XML in content when it
    # doesn't use the structured tool_calls field. The loop must recover them.
    content = (
        "Scrape returns 0 samples. Let me check.\n"
        "<\uFF5C\uFF5CDSML\uFF5C\uFF5Ctool_calls>\n"
        "<\uFF5C\uFF5CDSML\uFF5C\uFF5Cinvoke name=\"query_prometheus\">\n"
        "<\uFF5C\uFF5CDSML\uFF5C\uFF5Cparameter name=\"promql\" string=\"true\">up{job=\"node-exporter\"}</\uFF5C\uFF5CDSML\uFF5C\uFF5Cparameter>\n"
        "</\uFF5C\uFF5CDSML\uFF5C\uFF5Cinvoke>\n"
        "<\uFF5C\uFF5CDSML\uFF5C\uFF5Cinvoke name=\"query_loki_range\">\n"
        "<\uFF5C\uFF5CDSML\uFF5C\uFF5Cparameter name=\"limit\" string=\"false\">50</\uFF5C\uFF5CDSML\uFF5C\uFF5Cparameter>\n"
        "<\uFF5C\uFF5CDSML\uFF5C\uFF5Cparameter name=\"logql\" string=\"true\">{job=\"prometheus\"}</\uFF5C\uFF5CDSML\uFF5C\uFF5Cparameter>\n"
        "<\uFF5C\uFF5CDSML\uFF5C\uFF5Cparameter name=\"minutes\" string=\"false\">30</\uFF5C\uFF5CDSML\uFF5C\uFF5Cparameter>\n"
        "</\uFF5C\uFF5CDSML\uFF5C\uFF5Cinvoke>\n"
        "</\uFF5C\uFF5CDSML\uFF5C\uFF5Ctool_calls>"
    )
    calls = _parse_dsml_calls(content)
    assert [c["name"] for c in calls] == ["query_prometheus", "query_loki_range"]
    assert calls[0]["args"] == {"promql": 'up{job="node-exporter"}'}
    assert calls[1]["args"] == {"limit": 50, "logql": '{job="prometheus"}', "minutes": 30}


def test_strip_dsml_leaves_prose_and_removes_markup():
    content = (
        "Diagnosis prose here.\n"
        "<\uFF5C\uFF5CDSML\uFF5C\uFF5Ctool_calls>\n"
        "<\uFF5C\uFF5CDSML\uFF5C\uFF5Cinvoke name=\"query_prometheus\">\n"
        "<\uFF5C\uFF5CDSML\uFF5C\uFF5Cparameter name=\"promql\" string=\"true\">up</\uFF5C\uFF5CDSML\uFF5C\uFF5Cparameter>\n"
        "</\uFF5C\uFF5CDSML\uFF5C\uFF5Cinvoke>\n"
        "</\uFF5C\uFF5CDSML\uFF5C\uFF5Ctool_calls>"
    )
    out = _strip_dsml(content)
    assert "DSML" not in out
    assert "Diagnosis prose here." in out
