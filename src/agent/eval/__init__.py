"""Automated scenario evaluation harness.

Parses scenario YAML files and checks whether observed agent tool calls
match the ``expected_agent_actions`` declared in each scenario.

The harness is a *pure checker* — it does not run the agent.  The test or
CLI is responsible for invoking the investigation and collecting tool-call
names, then passing them to :meth:`EvalHarness.evaluate`.

CLI usage::

    python -m agent eval              # run all scenarios against real LLM
    python -m agent eval --scenario scenarios/container_down.yml
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

import yaml


_ACTION_TO_TOOLS: dict[str, list[str]] = {
    "retrieve service status": ["list_services", "docker_status"],
    "query docker for container state": ["docker_status"],
    "check endpoint health": ["check_endpoint"],
    "query prometheus for cpu usage": [
        "list_metric_names",
        "query_prometheus",
        "query_prometheus_range",
    ],
    "query prometheus for memory usage": [
        "list_metric_names",
        "query_prometheus",
        "query_prometheus_range",
    ],
    "query prometheus for response latency": [
        "list_metric_names",
        "query_prometheus",
        "query_prometheus_range",
    ],
    "query prometheus for request rate": [
        "list_metric_names",
        "query_prometheus",
        "query_prometheus_range",
    ],
    "query prometheus for disk usage metrics": [
        "list_metric_names",
        "query_prometheus",
        "query_prometheus_range",
    ],
    "query prometheus for certificate expiry metric": [
        "list_metric_names",
        "query_prometheus",
        "query_prometheus_range",
    ],
    "query prometheus range for memory trend": [
        "query_prometheus_range",
    ],
    "discover relevant metric names": ["list_metric_names", "get_label_values"],
    "query loki for recent error logs": [
        "query_loki",
        "query_loki_range",
    ],
    "query loki for error logs": [
        "query_loki",
        "query_loki_range",
    ],
    "query loki for disk-related errors": [
        "query_loki",
        "query_loki_range",
    ],
    "query loki for timeout errors": [
        "query_loki",
        "query_loki_range",
    ],
    "query loki for recent warnings": [
        "query_loki",
        "query_loki_range",
    ],
    "query loki for tls-related log entries": [
        "query_loki",
        "query_loki_range",
    ],
    "query loki for slow query logs": [
        "query_loki",
        "query_loki_range",
    ],
    "query loki for request logs": [
        "query_loki",
        "query_loki_range",
    ],
    "summarize findings": [],
    "store incident": [],
    "alert discord channel if configured": [],
}

# Pre-built lowercase index for case-insensitive matching.
_ACTION_INDEX: dict[str, list[str]] = {
    k.lower(): v for k, v in _ACTION_TO_TOOLS.items()
}


@dataclass
class EvalResult:
    """Structured outcome of a single scenario evaluation."""

    scenario: str
    service: str
    passed: bool
    total_actions: int
    matched_actions: int
    missing_actions: list[str] = field(default_factory=list)
    actual_tool_calls: list[str] = field(default_factory=list)
    final_summary: str = ""
    error: str | None = None

    @property
    def score(self) -> float:
        if self.total_actions == 0:
            return 1.0
        return self.matched_actions / self.total_actions


class EvalHarness:
    """Loads a scenario YAML and checks tool calls against expectations.

    Call :meth:`evaluate` with the list of tool-call names actually observed
    during the investigation.
    """

    def __init__(self, scenario_path: str | Path) -> None:
        self._path = Path(scenario_path)
        if not self._path.exists():
            raise FileNotFoundError(f"Scenario not found: {self._path}")
        self._scenario = yaml.safe_load(self._path.read_text(encoding="utf-8"))

    @property
    def name(self) -> str:
        return self._scenario.get("name", self._path.stem)

    @property
    def service(self) -> str:
        return self._scenario.get("service", "unknown")

    @property
    def symptom(self) -> str:
        return self._scenario.get("symptom", "")

    def expected_actions(self) -> list[str]:
        return self._scenario.get("expected_agent_actions", [])

    def _map_action_to_tools(self, action: str) -> list[str]:
        return _ACTION_INDEX.get(action.lower(), [])

    def evaluate(self, *, tool_calls: list[str], summary: str = "", error: str | None = None) -> EvalResult:
        """Check whether *tool_calls* satisfy the expected actions.

        ``tool_calls`` is the list of tool function names (strings) called by
        the agent during investigation.
        """
        result = EvalResult(
            scenario=self.name,
            service=self.service,
            passed=False,
            total_actions=0,
            matched_actions=0,
            actual_tool_calls=tool_calls,
            final_summary=summary,
            error=error,
        )

        actions = self.expected_actions()
        result.total_actions = len(actions)

        for action in actions:
            expected_tools = self._map_action_to_tools(action)
            if not expected_tools:
                result.matched_actions += 1
                continue
            if any(tool in tool_calls for tool in expected_tools):
                result.matched_actions += 1
            else:
                result.missing_actions.append(action)

        result.passed = result.matched_actions == result.total_actions
        return result


def discover_scenarios(root: str | Path = "scenarios") -> list[EvalHarness]:
    """Return a harness for every ``*.yml`` file under *root*."""
    root = Path(root)
    if not root.is_dir():
        return []
    harnesses: list[EvalHarness] = []
    for path in sorted(root.glob("*.yml")):
        try:
            harnesses.append(EvalHarness(path))
        except Exception:
            continue
    return harnesses
