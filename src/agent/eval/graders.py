"""Code-based graders that score one aspect of a trial.

Each grader takes the harness (for task config) plus the observed trial
outputs and returns a :class:`GraderResult`. Graders reference the harness
only via duck-typed ``"EvalHarness"`` string hints, so this module has no
dependency on :mod:`agent.eval.harness` (the harness imports the graders,
not the reverse).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class GraderResult:
    """Outcome of a single grader on a single trial."""

    name: str
    passed: bool
    detail: str = ""


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

_METRIC_FAMILY_RE = {
    "latency": re.compile(r"histogram_quantile|latency|duration|request_duration", re.IGNORECASE),
    "request_rate": re.compile(r"rate\(.*request|http_requests|requests_total|request_rate", re.IGNORECASE),
    "cpu": re.compile(r"cpu", re.IGNORECASE),
    "memory": re.compile(r"memory|resident|heap", re.IGNORECASE),
}


def _grade_tool_calls(harness, *, tool_calls, summary, transcript, proposals) -> GraderResult:
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


def _grade_no_raw_markup(harness, *, tool_calls, summary, transcript, proposals) -> GraderResult:
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


def _grade_groundedness(harness, *, tool_calls, summary, transcript, proposals) -> GraderResult:
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


def _grade_no_false_alarm(harness, *, tool_calls, summary, transcript, proposals) -> GraderResult:
    if harness.kind != "negative":
        return GraderResult("no_false_alarm", True, "n/a (task is not 'negative')")
    m = _ALARM_WORDS_RE.search(summary)
    return GraderResult(
        "no_false_alarm",
        m is None,
        "clean" if m is None else f"escalation word: {m.group(0)!r}",
    )


def _grade_no_hallucination(harness, *, tool_calls, summary, transcript, proposals) -> GraderResult:
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


def _grade_right_source(harness, *, tool_calls, summary, transcript, proposals) -> GraderResult:
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


def _grade_right_metric(harness, *, tool_calls, summary, transcript, proposals) -> GraderResult:
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


def _grade_right_container(harness, *, tool_calls, summary, transcript, proposals) -> GraderResult:
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


def _grade_exactly_one(harness, *, tool_calls, summary, transcript, proposals) -> GraderResult:
    """For ``kind: remediation`` tasks, exactly one restart was proposed (no spam)."""
    if harness.kind != "remediation":
        return GraderResult("exactly_one", True, "n/a (task is not 'remediation')")
    n = len(proposals or [])
    return GraderResult("exactly_one", n == 1, f"{n} proposals")


# Ordered list applied to every trial in :meth:`EvalHarness.evaluate`.
GRADERS = [
    _grade_tool_calls,
    _grade_no_raw_markup,
    _grade_groundedness,
    _grade_no_false_alarm,
    _grade_no_hallucination,
    _grade_right_source,
    _grade_right_metric,
    _grade_right_container,
    _grade_exactly_one,
]
