"""Automated scenario evaluation tests.

Each scenario YAML in ``scenarios/`` is loaded by :class:`EvalHarness`,
run through a mocked agentic loop, and checked against its declared
``expected_agent_actions``.

The LLM is simulated with canned tool calls that match each scenario's
expected actions, so this is a *harness-verification* test (not a live
LLM test).  For end-to-end LLM evaluation, use ``!scenario`` on Discord
or ``python -m agent eval``.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agent.eval import EvalHarness, discover_scenarios
from agent.workflows import incident as incident_module
from agent.workflows.incident import (
    INCIDENT_SYSTEM_PROMPT,
    run_agentic_investigation_stream,
)
from agent.tools import query_tools


class FakeMessage:
    def __init__(self, content: str = "", tool_calls: list | None = None):
        self.content = content
        self.tool_calls = tool_calls or []


class FakeLLM:
    def __init__(self, responses: list):
        self._responses = responses
        self._index = 0

    def bind_tools(self, _tools):
        return self

    async def ainvoke(self, _messages):
        resp = self._responses[self._index]
        self._index += 1
        return resp


@pytest.fixture
def patched_sources(monkeypatch):
    """Patch Prometheus/Loki source functions so no network calls happen."""
    prom = AsyncMock(return_value={"data": {"result": [{"value": [1, "85"]}]}})
    prom_range = AsyncMock(
        return_value={"data": {"result": [{"values": [[1, "40"], [2, "60"]]}]}}
    )
    names = AsyncMock(return_value=["cpu_usage", "memory_usage"])
    labels = AsyncMock(return_value=["web", "api"])
    loki_q = AsyncMock(return_value={"data": {"result": [{"values": [[1, "ERROR: down"]]}]}})

    monkeypatch.setattr(query_tools.prometheus, "query_prometheus", prom)
    monkeypatch.setattr(query_tools.prometheus, "query_prometheus_range", prom_range)
    monkeypatch.setattr(query_tools.prometheus, "list_metric_names", names)
    monkeypatch.setattr(query_tools.prometheus, "get_label_values", labels)
    monkeypatch.setattr(query_tools.loki, "query_loki", loki_q)
    monkeypatch.setattr(query_tools.loki, "query_loki_range", loki_q)

    return {
        "query_prometheus": prom,
        "query_prometheus_range": prom_range,
        "list_metric_names": names,
        "get_label_values": labels,
        "query_loki": loki_q,
        "query_loki_range": loki_q,
    }


_SCENARIO_TOOL_CALLS: dict[str, list[dict]] = {
    "sample_slow_query": [
        {"name": "list_services", "args": {}, "id": "c1"},
        {"name": "query_prometheus", "args": {"promql": "rate(cpu_usage[5m])"}, "id": "c2"},
        {"name": "query_loki", "args": {"logql": '{service="postgres"} |= "slow"', "limit": 50}, "id": "c3"},
    ],
    "container_down": [
        {"name": "list_services", "args": {}, "id": "c1"},
        {"name": "docker_status", "args": {"container": "app"}, "id": "c2"},
        {"name": "query_loki", "args": {"logql": '{service="app"} |= "error"', "limit": 50}, "id": "c3"},
    ],
    "high_cpu": [
        {"name": "list_services", "args": {}, "id": "c1"},
        {"name": "list_metric_names", "args": {"match": "cpu"}, "id": "c2"},
        {"name": "query_prometheus", "args": {"promql": "cpu_usage"}, "id": "c3"},
        {"name": "query_loki", "args": {"logql": '{service="api"} |= "error"', "limit": 50}, "id": "c4"},
    ],
    "endpoint_timeout": [
        {"name": "list_services", "args": {}, "id": "c1"},
        {"name": "query_loki", "args": {"logql": '{service="web"} |~ "timeout|504"', "limit": 50}, "id": "c2"},
        {"name": "query_prometheus", "args": {"promql": "http_request_duration_seconds"}, "id": "c3"},
    ],
    "disk_full": [
        {"name": "list_services", "args": {}, "id": "c1"},
        {"name": "docker_status", "args": {"container": "postgres"}, "id": "c2"},
        {"name": "query_loki", "args": {"logql": '{service="postgres"} |= "disk"', "limit": 50}, "id": "c3"},
    ],
    "memory_leak": [
        {"name": "list_services", "args": {}, "id": "c1"},
        {"name": "list_metric_names", "args": {"match": "memory"}, "id": "c2"},
        {"name": "query_prometheus_range", "args": {"promql": "memory_usage", "minutes": 60}, "id": "c3"},
        {"name": "query_loki", "args": {"logql": '{service="worker"} |= "warn"', "limit": 50}, "id": "c4"},
    ],
    "certificate_expiry": [
        {"name": "list_services", "args": {}, "id": "c1"},
        {"name": "list_metric_names", "args": {"match": "cert"}, "id": "c2"},
        {"name": "query_prometheus", "args": {"promql": "ssl_expiry_days"}, "id": "c3"},
        {"name": "query_loki", "args": {"logql": '{service="ingress"} |~ "TLS|tls|cert"', "limit": 50}, "id": "c4"},
    ],
}

_SCENARIO_ANSWERS: dict[str, str] = {
    "sample_slow_query": "Slow query caused CPU spike.",
    "container_down": "Container app is stopped.",
    "high_cpu": "CPU usage at 90%.",
    "endpoint_timeout": "Web endpoint returning 504.",
    "disk_full": "Postgres data volume full.",
    "memory_leak": "Worker process memory leak.",
    "certificate_expiry": "TLS cert expires in 3 days.",
}


async def _run_scenario(service: str, tools: list[dict], answer: str) -> list[str]:
    """Run a single investigation through the agentic loop with a mocked LLM."""
    calls: list[str] = []
    async for event in run_agentic_investigation_stream(
        f"Investigate service {service}.",
        system_prompt=INCIDENT_SYSTEM_PROMPT,
        kind="incident",
    ):
        if event["type"] == "tool_call":
            calls.append(event["name"])
    return calls


def _load_scenario_paths():
    root = Path(__file__).resolve().parents[2] / "scenarios"
    return sorted(root.glob("*.yml"))


def _scenario_stem(path: Path) -> str:
    return path.stem


@pytest.mark.parametrize(
    "scenario_path",
    _load_scenario_paths(),
    ids=_scenario_stem,
)
def test_scenario_eval_passes(
    scenario_path, tmp_database, patched_sources, monkeypatch
):
    """Every scenario must pass its expected_agent_actions check."""
    stem = scenario_path.stem
    tools = _SCENARIO_TOOL_CALLS.get(
        stem,
        [{"name": "list_services", "args": {}, "id": "c1"}],
    )
    answer = _SCENARIO_ANSWERS.get(stem, "Investigation summary.")

    harness = EvalHarness(scenario_path)

    responses = [
        FakeMessage(content="", tool_calls=tools),
        FakeMessage(content=answer),
    ]

    from agent.config.settings import Settings

    monkeypatch.setattr(incident_module, "settings", Settings(max_tool_steps=6, _env_file=None))

    with patch("agent.workflows.incident.get_llm", return_value=FakeLLM(responses)):
        calls = asyncio.run(_run_scenario(harness.service, tools, answer))

    result = harness.evaluate(tool_calls=calls, summary=answer)

    assert result.passed, (
        f"Scenario '{result.scenario}' failed: "
        f"{result.matched_actions}/{result.total_actions} actions matched. "
        f"Missing: {result.missing_actions}. "
        f"Actual tool calls: {result.actual_tool_calls}"
    )


def test_all_scenarios_parse():
    """Every .yml in scenarios/ must parse as a valid EvalHarness."""
    for h in discover_scenarios():
        actions = h.expected_actions()
        assert len(actions) > 0, f"{h.name}: no expected_agent_actions"
        assert h.service, f"{h.name}: no service"


def test_container_down_scenario_calls_docker_status(tmp_database, patched_sources, monkeypatch):
    """Verify the 'container_down' scenario triggers docker_status specifically."""
    tools = _SCENARIO_TOOL_CALLS["container_down"]
    answer = _SCENARIO_ANSWERS["container_down"]
    responses = [FakeMessage(content="", tool_calls=tools), FakeMessage(content=answer)]

    from agent.config.settings import Settings

    monkeypatch.setattr(incident_module, "settings", Settings(max_tool_steps=6, _env_file=None))

    with patch("agent.workflows.incident.get_llm", return_value=FakeLLM(responses)):
        calls = asyncio.run(_run_scenario("app", tools, answer))

    harness = EvalHarness("scenarios/container_down.yml")
    result = harness.evaluate(tool_calls=calls)

    assert result.passed
    assert "docker_status" in result.actual_tool_calls
    assert result.score >= 0.7


def test_memory_leak_scenario_calls_range_query(tmp_database, patched_sources, monkeypatch):
    """The memory_leak scenario should query a Prometheus range."""
    tools = _SCENARIO_TOOL_CALLS["memory_leak"]
    answer = _SCENARIO_ANSWERS["memory_leak"]
    responses = [FakeMessage(content="", tool_calls=tools), FakeMessage(content=answer)]

    from agent.config.settings import Settings

    monkeypatch.setattr(incident_module, "settings", Settings(max_tool_steps=6, _env_file=None))

    with patch("agent.workflows.incident.get_llm", return_value=FakeLLM(responses)):
        calls = asyncio.run(_run_scenario("worker", tools, answer))

    harness = EvalHarness("scenarios/memory_leak.yml")
    result = harness.evaluate(tool_calls=calls)

    assert result.passed
    assert "query_prometheus_range" in result.actual_tool_calls
    patched_sources["query_prometheus_range"].assert_awaited()
