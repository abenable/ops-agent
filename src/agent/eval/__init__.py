"""Automated task evaluation harness.

Parses task YAML files and grades observed agent behavior against the
declared expectations using one or more *graders*.

Vocabulary (after Anthropic, "Demystifying evals for AI agents"):
- A *task* is one YAML file under ``tasks/`` (a problem / test case).
- A *trial* is one attempt at a task. The CLI runs N trials per task
  (``--trials N``) and records pass@k / pass^k.
- A *grader* scores one aspect of a trial. A task can have several graders;
  the trial passes only if every applicable grader passes (partial credit:
  the trial score is the fraction of graders that passed).
- A *transcript* is the full event trace of a trial (tool_call / tool_result /
  done), saved to disk per trial.

Built-in graders (code-based):
- ``tool_calls``   — the agent called a tool from each expected action's set.
- ``no_raw_markup``— the summary has no leaked ``<｜｜DSML｜｜>`` XML and no
  raw markdown table rows (Discord renders ``|`` as a wall of pipes).
- ``groundedness`` — each ``expected_evidence`` string appears in the summary
  (coverage); when a transcript is supplied, evidence must also appear in a
  ``tool_result`` event (grounded in observed data, not invented).
- ``no_false_alarm``— for ``kind: negative`` tasks, the summary does not assert
  a problem (no escalation words). Validates the agent does not over-alarm on
  healthy services.
- ``no_hallucination``— each ``forbidden_containers`` entry is absent from the
  summary (the agent did not act on a name not in the observed inventory).
- ``right_source`` — for ``kind: logs`` tasks, the declared ``expected_source``
  (loki | docker_logs | either) was called.

The harness is a *pure checker* — it does not run the agent.  The CLI is
responsible for invoking the investigation, collecting tool-call names and the
summary, then passing them to :meth:`EvalHarness.evaluate`.

CLI usage::

    python -m agent eval                      # run all tasks, 1 trial each
    python -m agent eval --task tasks/api_down.yml
    python -m agent eval --trials 5 --label qwen2.5-14b   # pass@k / pass^k
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# DSML inline tool-call marker DeepSeek sometimes emits in ``content`` instead
# of the OpenAI ``tool_calls`` field. See ``workflows.incident._parse_dsml_calls``.
_PIPE = "\uFF5C"
_DSML_MARKER = _PIPE + _PIPE + "DSML" + _PIPE + _PIPE
# Markdown table row: ``| a | b |`` — Discord renders this as a wall of pipes.
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)

# Words a healthy-service summary should not contain (``no_false_alarm`` grader).
# Word-boundary regex so "down" does not match "download".
_ALARM_WORDS_RE = re.compile(
    r"\b(down|unreachable|stopped|crash|crashed|killed|oom|fail|failed|failure|"
    r"error|errors|unhealthy|not responding|not reachable)\b",
    re.IGNORECASE,
)


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
class GraderResult:
    """Outcome of a single grader on a single trial."""

    name: str
    passed: bool
    detail: str = ""


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


# --- graders ----------------------------------------------------------------

def _grade_tool_calls(harness: "EvalHarness", tool_calls: list[str]) -> GraderResult:
    actions = harness.expected_actions()
    if not actions:
        return GraderResult("tool_calls", True, "no expected actions")
    matched = 0
    missing: list[str] = []
    for action in actions:
        expected_tools = harness._map_action_to_tools(action)
        if not expected_tools:
            matched += 1
            continue
        if any(tool in tool_calls for tool in expected_tools):
            matched += 1
        else:
            missing.append(action)
    passed = matched == len(actions)
    detail = f"{matched}/{len(actions)} actions" + (
        f"; missing: {', '.join(missing)}" if missing else ""
    )
    return GraderResult("tool_calls", passed, detail)


def _grade_no_raw_markup(_harness: "EvalHarness", summary: str) -> GraderResult:
    problems: list[str] = []
    if _DSML_MARKER in summary:
        problems.append("DSML XML leaked into summary")
    if _TABLE_ROW_RE.search(summary):
        problems.append("markdown table row present (Discord renders | as pipes)")
    return GraderResult(
        "no_raw_markup",
        not problems,
        "; ".join(problems) if problems else "clean",
    )


def _grade_groundedness(harness: "EvalHarness", summary: str, transcript: list[dict] | None) -> GraderResult:
    """Each ``expected_evidence`` string must appear in the trial.

    With a transcript, evidence must appear in a ``tool_result`` event
    (grounded in observed data, not invented). Without a transcript, evidence
    must appear in the summary (coverage) — the weaker backward-compatible path
    used by the mocked harness-verification tests.
    """
    evidence = harness.expected_evidence()
    if not evidence:
        return GraderResult("groundedness", True, "no expected_evidence declared")
    if transcript:
        result_text = " ".join(str(e.get("result", "")) for e in transcript if e.get("type") == "tool_result").lower()
        missing = [e for e in evidence if e.lower() not in result_text]
        where = "tool_result"
    else:
        low = summary.lower()
        missing = [e for e in evidence if e.lower() not in low]
        where = "summary"
    return GraderResult(
        "groundedness",
        not missing,
        f"{len(evidence) - len(missing)}/{len(evidence)} in {where}"
        + (f"; missing: {', '.join(missing)}" if missing else ""),
    )


def _grade_no_false_alarm(harness: "EvalHarness", summary: str) -> GraderResult:
    if harness.kind != "negative":
        return GraderResult("no_false_alarm", True, "n/a (task is not 'negative')")
    m = _ALARM_WORDS_RE.search(summary)
    return GraderResult(
        "no_false_alarm",
        m is None,
        "clean" if m is None else f"escalation word: {m.group(0)!r}",
    )


def _grade_no_hallucination(harness: "EvalHarness", summary: str) -> GraderResult:
    """Each ``forbidden_containers`` entry must be absent from the summary.

    Catches the agent acting on a container name not in the observed inventory
    (e.g. an @mention that names a hallucinated service). Opt-in per task.
    """
    forbidden = harness.forbidden_containers()
    if not forbidden:
        return GraderResult("no_hallucination", True, "no forbidden_containers declared")
    low = summary.lower()
    leaked = [c for c in forbidden if c.lower() in low]
    return GraderResult(
        "no_hallucination",
        not leaked,
        "clean" if not leaked else f"hallucinated: {', '.join(leaked)}",
    )


def _grade_right_source(harness: "EvalHarness", tool_calls: list[str]) -> GraderResult:
    """For ``kind: logs`` tasks, the declared ``expected_source`` was called."""
    if harness.kind != "logs":
        return GraderResult("right_source", True, "n/a (task is not 'logs')")
    src = (harness.expected_source() or "either").lower()
    loki_called = any(t in tool_calls for t in ("query_loki", "query_loki_range"))
    docker_called = "docker_logs" in tool_calls
    if src == "loki":
        passed, detail = loki_called, "loki" if loki_called else "loki not called"
    elif src == "docker_logs":
        passed, detail = docker_called, "docker_logs" if docker_called else "docker_logs not called"
    else:
        passed, detail = loki_called or docker_called, "loki or docker_logs"
    return GraderResult("right_source", passed, detail)


_METRIC_FAMILY_RE = {
    "latency": re.compile(r"histogram_quantile|latency|duration|request_duration", re.IGNORECASE),
    "request_rate": re.compile(r"rate\(.*request|http_requests|requests_total|request_rate", re.IGNORECASE),
    "cpu": re.compile(r"cpu", re.IGNORECASE),
    "memory": re.compile(r"memory|resident|heap", re.IGNORECASE),
}


def _grade_right_metric(harness: "EvalHarness", transcript: list[dict] | None) -> GraderResult:
    """For ``kind: perf`` tasks, the declared ``expected_metric_family`` was queried.

    Inspects the PromQL in ``query_prometheus`` tool_call args in the transcript.
    Without a transcript the grader is n/a (the mocked harness tests don't pass
    one); the live CLI path does the real check.
    """
    if harness.kind != "perf":
        return GraderResult("right_metric", True, "n/a (task is not 'perf')")
    family = (harness.expected_metric_family() or "").lower()
    if not family:
        return GraderResult("right_metric", True, "no expected_metric_family declared")
    if not transcript:
        return GraderResult("right_metric", True, "n/a (no transcript)")
    promqls = [
        str(e.get("args", {}).get("promql", ""))
        for e in transcript
        if e.get("type") == "tool_call" and e.get("name") in ("query_prometheus", "query_prometheus_range")
    ]
    if not promqls:
        return GraderResult("right_metric", False, "no query_prometheus call in transcript")
    pat = _METRIC_FAMILY_RE.get(family)
    if pat is None:
        return GraderResult("right_metric", False, f"unknown metric family: {family}")
    matched = [q for q in promqls if pat.search(q)]
    return GraderResult(
        "right_metric",
        bool(matched),
        f"{len(matched)}/{len(promqls)} PromQL match {family}"
        + (f"; e.g. {matched[0][:60]}" if matched else f"; none match (e.g. {promqls[0][:60]})"),
    )


def _grade_right_container(harness: "EvalHarness", proposals: list[dict] | None) -> GraderResult:
    """For ``kind: remediation`` tasks, the proposed container matches the expected one."""
    if harness.kind != "remediation":
        return GraderResult("right_container", True, "n/a (task is not 'remediation')")
    expected = (harness.expected_remediation_container() or "").lower()
    if not expected:
        return GraderResult("right_container", True, "no expected_remediation_container declared")
    if not proposals:
        return GraderResult("right_container", False, "no proposals")
    names = " ".join(str(p.get("container_name", "")) for p in proposals).lower()
    return GraderResult(
        "right_container",
        expected in names,
        f"proposed: {names!r}; expected {expected!r}",
    )


def _grade_exactly_one(harness: "EvalHarness", proposals: list[dict] | None) -> GraderResult:
    """For ``kind: remediation`` tasks, exactly one restart was proposed (no spam)."""
    if harness.kind != "remediation":
        return GraderResult("exactly_one", True, "n/a (task is not 'remediation')")
    n = len(proposals or [])
    return GraderResult("exactly_one", n == 1, f"{n} proposals")


class EvalHarness:
    """Loads a task YAML and grades a trial against the applicable graders.

    Call :meth:`evaluate` with the list of tool-call names actually observed
    and the final summary the agent produced.
    """

    def __init__(self, task_path: str | Path) -> None:
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

    def expected_actions(self) -> list[str]:
        return self._task.get("expected_agent_actions", [])

    def expected_evidence(self) -> list[str]:
        return self._task.get("expected_evidence", [])

    def forbidden_containers(self) -> list[str]:
        return self._task.get("forbidden_containers", [])

    def expected_source(self) -> str:
        return self._task.get("expected_source", "")

    def expected_metric_family(self) -> str:
        return self._task.get("expected_metric_family", "")

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
        """
        if not self.reference_summary() and not self.reference_tool_calls() and self.kind != "remediation":
            return EvalResult(task=self.name, service=self.service, passed=True, total_actions=0, matched_actions=0, actual_tool_calls=[], final_summary="", error=None)
        if self.kind == "remediation":
            proposals = [{"container_name": self.expected_remediation_container()}]
            return self.evaluate(tool_calls=["propose_restart"], summary=self.reference_summary(), proposals=proposals)
        return self.evaluate(tool_calls=self.reference_tool_calls(), summary=self.reference_summary())

    def history(self) -> list[dict]:
        """Prior conversational turns to feed into the investigation (multi-turn)."""
        return self._task.get("history", []) or []

    def _map_action_to_tools(self, action: str) -> list[str]:
        return _ACTION_INDEX.get(action.lower(), [])

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
            _grade_tool_calls(self, tool_calls),
            _grade_no_raw_markup(self, summary),
            _grade_groundedness(self, summary, transcript),
            _grade_no_false_alarm(self, summary),
            _grade_no_hallucination(self, summary),
            _grade_right_source(self, tool_calls),
            _grade_right_metric(self, transcript),
            _grade_right_container(self, proposals),
            _grade_exactly_one(self, proposals),
        ]
        result.passed = all(g.passed for g in result.graders) and not error
        return result


def discover_tasks(root: str | Path = "tasks") -> list[EvalHarness]:
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


def aggregate_trials(results: list[EvalResult]) -> dict:
    """Aggregate N trials of one task into pass@k / pass^k statistics.

    - ``pass_at_k``: probability at least one trial passed (>= 1 success in k).
    - ``pass_k``:    probability all trials passed (consistency).
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
