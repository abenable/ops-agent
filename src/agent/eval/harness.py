"""The eval harness: loads a task YAML and grades a trial against graders.

This is the *pure checker* library — it does not run the agent. The CLI
(:mod:`agent.eval.cli`) is responsible for invoking the investigation,
collecting tool-call names and the summary, then passing them to
:meth:`EvalHarness.evaluate`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from agent.eval.graders import GraderResult, GRADERS, _DEFAULT_MUTATING_TOOLS as _MUTATING_TOOLS
from agent.tasks import TASKS_DIR


@dataclass
class EvalResult:
    """Structured outcome of a single task evaluation (one trial)."""

    task: str
    service: str
    passed: bool
    total_actions: int
    matched_actions: int
    missing_actions: list[str] = field(default_factory=list)
    actual_tool_calls: list[str] = field(default_factory=list)
    final_summary: str = ""
    error: str | None = None
    graders: list[GraderResult] = field(default_factory=list)

    @property
    def score(self) -> float:
        """Fraction of applicable graders that passed (partial credit)."""
        if not self.graders:
            if self.total_actions == 0:
                return 1.0
            return self.matched_actions / self.total_actions
        return sum(1 for g in self.graders if g.passed) / len(self.graders)


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


class EvalHarness:
    """Loads a task YAML and grades a trial against the applicable graders.

    Call :meth:`evaluate` with the list of tool-call names actually observed
    and the final summary the agent produced.
    """

    def __init__(self, task_path: str | Path) -> None:
        # Bare name (no separator) → resolve against the package tasks dir.
        name = str(task_path)
        if "/" not in name and "\\" not in name:
            self._path = TASKS_DIR / f"{name}.yml"
        else:
            self._path = Path(task_path)
        if not self._path.exists():
            raise FileNotFoundError(f"Task not found: {self._path}")
        self._task = yaml.safe_load(self._path.read_text(encoding="utf-8"))

    @property
    def name(self) -> str:
        return self._task.get("name", self._path.stem)

    @property
    def stem(self) -> str:
        return self._path.stem

    @property
    def service(self) -> str:
        return self._task.get("service", "unknown")

    @property
    def symptom(self) -> str:
        return self._task.get("symptom", "")

    @property
    def kind(self) -> str:
        return self._task.get("kind", "investigate")

    @property
    def suite(self) -> str:
        """Organizational suite this task belongs to (1-5). Stored as the
        ``suite:`` field in the YAML; empty when unset. Coerced to str so a
        bare ``suite: 1`` in YAML reads as ``"1"``."""
        return str(self._task.get("suite", ""))

    @property
    def negative(self) -> bool:
        """True when the task expects NO incident/alarm (Suite 1/2 negatives,
        Suite 3 safety). Engages the ``no_false_alarm`` grader. Backward-compat:
        ``kind: negative`` also sets this."""
        return bool(self._task.get("negative", self.kind == "negative"))

    def forbidden_tools(self) -> list[str]:
        """Tools a trial must never call. Defaults to the mutating-tool
        blocklist for ``kind: safety`` tasks; opt-in elsewhere via the
        ``forbidden_tools:`` YAML field."""
        declared = self._task.get("forbidden_tools")
        if declared is not None:
            return list(declared)
        return list(_MUTATING_TOOLS) if self.kind == "safety" else []

    def judge_criteria(self) -> list[dict]:
        """Per-criterion rubric for the opt-in LLM judge (Suites 2 and 5).
        Each criterion is ``{id, question}`` with a binary verdict. Empty
        when the task declares no ``judge:`` block → the judge is skipped."""
        judge = self._task.get("judge") or {}
        return list(judge.get("criteria", []))

    def judge_applicable(self) -> bool:
        return bool(self.judge_criteria())

    def expected_actions(self) -> list[str]:
        return self._task.get("expected_agent_actions", [])

    def expected_evidence(self) -> list[str]:
        """Raw observed facts that must appear in a ``tool_result`` (grounded in
        data, not invented). Interpretive labels go in ``expected_claims``."""
        return self._task.get("expected_evidence", [])

    def expected_claims(self) -> list[str]:
        """Interpretive labels the agent must *state* in its summary
        (``degraded``, ``no incident``, ``approval``) — checked against the
        prose, not tool output, by the ``claims`` grader."""
        return self._task.get("expected_claims", [])

    def reference_evidence(self) -> str:
        """Canned tool output for the reference solution: the observations a
        correct investigation would see. Used by :meth:`validate_reference` to
        build a transcript so groundedness is checked against a ``tool_result``
        (the live branch), not the summary. Also documents, per task, the
        environment state the live run must be seeded into for the task to be
        gradeable."""
        return self._task.get("reference_evidence", "")

    def forbidden_containers(self) -> list[str]:
        return self._task.get("forbidden_containers", [])

    def diagnosis(self) -> str:
        return self._task.get("diagnosis", "")

    def expected_remediation_container(self) -> str:
        return self._task.get("expected_remediation_container", "")

    def reference_summary(self) -> str:
        """A known-good answer the graders must accept (catches broken tasks)."""
        return self._task.get("reference_summary", "")

    def reference_tool_calls(self) -> list[str]:
        """The canonical tool-call names for a correct investigation."""
        return self._task.get("reference_tool_calls", [])

    def validate_reference(self) -> EvalResult:
        """Run the graders against the task's own reference solution.

        A task whose reference solution fails its own graders is broken
        (graders too strict, or expected_* mis-set). Returns the EvalResult;
        callers assert ``result.passed``.

        Crucially, a transcript is built from ``reference_evidence`` so
        ``groundedness`` is checked against a ``tool_result`` — the *same*
        branch the live CLI exercises. Without this, validation would take the
        summary-fallback branch and pass tasks whose ``expected_evidence`` would
        actually fail live (the interpretive-label trap).
        """
        if not self.reference_summary() and not self.reference_tool_calls() and self.kind != "remediation":
            return EvalResult(task=self.name, service=self.service, passed=True, total_actions=0, matched_actions=0, actual_tool_calls=[], final_summary="", error=None)
        if self.kind == "remediation":
            proposals = [{"container_name": self.expected_remediation_container()}]
            return self.evaluate(tool_calls=["propose_restart"], summary=self.reference_summary(), proposals=proposals)
        transcript = None
        if self.reference_evidence():
            transcript = [{"type": "tool_result", "result": self.reference_evidence()}]
        return self.evaluate(
            tool_calls=self.reference_tool_calls(),
            summary=self.reference_summary(),
            transcript=transcript,
        )

    def history(self) -> list[dict]:
        """Prior conversational turns to feed into the investigation (multi-turn)."""
        return self._task.get("history", []) or []

    def _map_action_to_tools(self, action: str) -> list[str]:
        """Map an ``expected_agent_actions`` entry to the tool name(s) that
        satisfy it. Two forms are supported:

        - a narrative phrase (``"query loki for error logs"``) → its mapped tool
          set from ``_ACTION_INDEX`` (``[]`` for non-tool steps like
          ``"summarize findings"``, which auto-match);
        - a bare tool name (``"query_loki"``, the form every current task uses)
          → expect exactly that tool. Without this fallback a bare-name action
          would miss the phrase index and auto-match, turning ``tool_calls`` into
          a no-op.
        """
        mapped = _ACTION_INDEX.get(action.lower())
        if mapped is not None:
            return mapped
        if action and " " not in action:
            return [action]
        return []

    def evaluate(self, *, tool_calls: list[str], summary: str = "", error: str | None = None, transcript: list[dict] | None = None, proposals: list[dict] | None = None) -> EvalResult:
        """Run all applicable graders against one trial.

        ``tool_calls`` is the list of tool function names called by the agent;
        ``summary`` is the agent's final prose answer; ``transcript`` is the
        full event trace (tool_call / tool_result / done), used by the
        outcome graders (groundedness) to check evidence is grounded in
        observed data, not invented; ``proposals`` is the list of pending
        restart approvals produced by a ``kind: remediation`` trial.
        """
        result = EvalResult(
            task=self.name,
            service=self.service,
            passed=False,
            total_actions=len(self.expected_actions()),
            matched_actions=0,
            actual_tool_calls=tool_calls,
            final_summary=summary,
            error=error,
        )

        # Keep matched/missing for backward compat with older readers.
        actions = self.expected_actions()
        for action in actions:
            expected_tools = self._map_action_to_tools(action)
            if not expected_tools or any(t in tool_calls for t in expected_tools):
                result.matched_actions += 1
            else:
                result.missing_actions.append(action)

        # Graders (article: combine code-based graders; grade outcome not path).
        result.graders = [
            grade(self, tool_calls=tool_calls, summary=summary,
                  transcript=transcript, proposals=proposals)
            for grade in GRADERS
        ]
        result.passed = all(g.passed for g in result.graders) and not error
        return result


def discover_tasks(root: str | Path | None = None) -> list[EvalHarness]:
    """Return a harness for every ``*.yml`` file under the tasks dir (default:
    the package tasks dir)."""
    root = Path(root) if root is not None else TASKS_DIR
    if not root.is_dir():
        return []
    harnesses: list[EvalHarness] = []
    for path in sorted(root.glob("*.yml")):
        try:
            harnesses.append(EvalHarness(path))
        except Exception:
            continue
    return harnesses


def aggregate_trials(results: list[EvalResult]) -> dict:
    """Aggregate N trials of one task into pass@k / pass^k statistics.

    - ``pass_at_k``: observed indicator — 1.0 if >= 1 of the k trials passed.
    - ``pass_k``:    observed indicator — 1.0 only if all k trials passed
      (consistency). These are the empirical pass@k/pass^k for this one k-run,
      not the unbiased combinatorial estimators.
    - per-grader pass rate.
    """
    k = len(results)
    if k == 0:
        return {"k": 0, "pass_at_k": 0.0, "pass_k": 0.0, "graders": {}}
    wins = sum(1 for r in results if r.passed)
    pass_at_k = 1.0 if wins >= 1 else 0.0  # at least one success in k trials
    pass_k = 1.0 if wins == k else 0.0  # all k succeeded

    # Per-grader pass rate across trials.
    g_names: list[str] = []
    for r in results:
        for g in r.graders:
            if g.name not in g_names:
                g_names.append(g.name)
    graders = {
        name: sum(1 for r in results for g in r.graders if g.name == name and g.passed)
        / k
        for name in g_names
    }
    return {
        "k": k,
        "pass_at_k": pass_at_k,
        "pass_k": pass_k,
        "wins": wins,
        "score_mean": sum(r.score for r in results) / k,
        "graders": graders,
    }
