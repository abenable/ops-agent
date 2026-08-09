"""Automated task evaluation tests.

Each task YAML in ``tasks/`` is loaded by :class:`EvalHarness`,
run through a mocked agentic loop, and checked against its declared
``expected_agent_actions``.

The LLM is simulated with canned tool calls that match each task's
expected actions, so this is a *harness-verification* test (not a live
LLM test).  For end-to-end LLM evaluation, use ``/task`` on Discord
or ``python -m agent eval``.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agent.eval import EvalHarness, discover_tasks
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


_TASK_TOOL_CALLS: dict[str, list[dict]] = {
    "api_down": [
        {"name": "list_services", "args": {}, "id": "c1"},
        {"name": "docker_status", "args": {"container": "api"}, "id": "c2"},
        {"name": "docker_logs", "args": {"container": "marconi-agent-api", "tail": 50}, "id": "c3"},
        {"name": "query_prometheus", "args": {"promql": 'up{job="agent_api"}'}, "id": "c4"},
    ],
    "scrape_target_down": [
        {"name": "list_services", "args": {}, "id": "c1"},
        {"name": "docker_status", "args": {"container": "node-exporter"}, "id": "c2"},
        {"name": "list_metric_names", "args": {"match": "scrape"}, "id": "c3"},
        {"name": "get_label_values", "args": {"label": "job"}, "id": "c4"},
        {"name": "query_prometheus", "args": {"promql": 'up{job="node-exporter"}'}, "id": "c5"},
    ],
    "n8n_high_cpu": [
        {"name": "list_services", "args": {}, "id": "c1"},
        {"name": "docker_status", "args": {"container": "n8n"}, "id": "c2"},
        {"name": "list_metric_names", "args": {"match": "cpu"}, "id": "c3"},
        {"name": "query_prometheus", "args": {"promql": 'rate(n8n_process_cpu_seconds_total[5m])'}, "id": "c4"},
        {"name": "docker_logs", "args": {"container": "marconi-agent-n8n", "tail": 50}, "id": "c5"},
    ],
    "n8n_memory": [
        {"name": "list_services", "args": {}, "id": "c1"},
        {"name": "docker_status", "args": {"container": "n8n"}, "id": "c2"},
        {"name": "list_metric_names", "args": {"match": "memory"}, "id": "c3"},
        {"name": "query_prometheus", "args": {"promql": 'n8n_process_resident_memory_bytes'}, "id": "c4"},
        {"name": "docker_logs", "args": {"container": "marconi-agent-n8n", "tail": 50}, "id": "c5"},
    ],
    "loki_no_logs": [
        {"name": "list_services", "args": {}, "id": "c1"},
        {"name": "docker_status", "args": {"container": "n8n"}, "id": "c2"},
        {"name": "query_loki", "args": {"logql": '{job="n8n"}', "limit": 50}, "id": "c3"},
        {"name": "docker_logs", "args": {"container": "marconi-agent-promtail", "tail": 50}, "id": "c4"},
    ],
    "vllm_down": [
        {"name": "list_services", "args": {}, "id": "c1"},
        {"name": "docker_status", "args": {"container": "vllm"}, "id": "c2"},
        {"name": "docker_logs", "args": {"container": "vllm", "tail": 50}, "id": "c3"},
    ],
    "healthy_service": [
        {"name": "list_services", "args": {}, "id": "c1"},
        {"name": "docker_status", "args": {"container": "api"}, "id": "c2"},
    ],
    "logs_loki_hit": [
        {"name": "list_services", "args": {}, "id": "c1"},
        {"name": "query_loki", "args": {"logql": '{job="n8n"}', "limit": 50}, "id": "c2"},
    ],
    "logs_loki_miss": [
        {"name": "list_services", "args": {}, "id": "c1"},
        {"name": "query_loki", "args": {"logql": '{job="n8n"}', "limit": 50}, "id": "c2"},
        {"name": "docker_status", "args": {"container": "n8n"}, "id": "c3"},
        {"name": "docker_logs", "args": {"container": "marconi-agent-n8n", "tail": 50}, "id": "c4"},
    ],
    "status_running": [
        {"name": "list_services", "args": {}, "id": "c1"},
        {"name": "docker_status", "args": {"container": "api"}, "id": "c2"},
    ],
    "status_stopped_misnamed": [
        {"name": "list_services", "args": {}, "id": "c1"},
        {"name": "docker_status", "args": {"container": "agent_api"}, "id": "c2"},
    ],
    "perf_latency": [
        {"name": "list_services", "args": {}, "id": "c1"},
        {"name": "list_metric_names", "args": {"match": "latency"}, "id": "c2"},
        {"name": "query_prometheus", "args": {"promql": "histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))"}, "id": "c3"},
    ],
    "perf_request_rate": [
        {"name": "list_services", "args": {}, "id": "c1"},
        {"name": "list_metric_names", "args": {"match": "request"}, "id": "c2"},
        {"name": "query_prometheus", "args": {"promql": "rate(http_requests_total[5m])"}, "id": "c3"},
    ],
    "memory_resolve_that_container": [
        {"name": "list_services", "args": {}, "id": "c1"},
        {"name": "docker_status", "args": {"container": "n8n"}, "id": "c2"},
        {"name": "list_metric_names", "args": {"match": "memory"}, "id": "c3"},
        {"name": "query_prometheus", "args": {"promql": "n8n_process_resident_memory_bytes"}, "id": "c4"},
    ],
    "grounding_no_hallucination": [
        {"name": "list_services", "args": {}, "id": "c1"},
    ],
    "cascading_api_and_n8n": [
        {"name": "list_services", "args": {}, "id": "c1"},
        {"name": "docker_status", "args": {"container": "api"}, "id": "c2"},
        {"name": "query_prometheus", "args": {"promql": "rate(n8n_process_cpu_seconds_total[5m])"}, "id": "c3"},
        {"name": "query_loki", "args": {"logql": '{job="api"}', "limit": 50}, "id": "c4"},
    ],
}


# reference summaries live in the task YAMLs now (single source of truth).


async def _run_task(service: str, tools: list[dict], answer: str) -> list[str]:
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


def _load_task_paths():
    import yaml
    root = Path(__file__).resolve().parents[1] / "tasks"
    paths = []
    for p in sorted(root.glob("*.yml")):
        kind = (yaml.safe_load(p.read_text()).get("kind") or "investigate")
        if kind == "remediation":
            continue  # remediation is graded by proposals, not the investigation path
        paths.append(p)
    return paths


def _task_stem(path: Path) -> str:
    return path.stem


@pytest.mark.parametrize(
    "task_path",
    _load_task_paths(),
    ids=_task_stem,
)
def test_task_eval_passes(
    task_path, tmp_database, patched_sources, monkeypatch
):
    """Every task must pass its expected_agent_actions check."""
    stem = task_path.stem
    tools = _TASK_TOOL_CALLS.get(
        stem,
        [{"name": "list_services", "args": {}, "id": "c1"}],
    )

    harness = EvalHarness(task_path)
    answer = harness.reference_summary() or "Investigation summary."

    responses = [
        FakeMessage(content="", tool_calls=tools),
        FakeMessage(content=answer),
    ]

    from agent.config.settings import Settings

    monkeypatch.setattr(incident_module, "settings", Settings(max_tool_steps=6, _env_file=None))

    with patch("agent.workflows.incident.get_llm", return_value=FakeLLM(responses)):
        calls = asyncio.run(_run_task(harness.service, tools, answer))

    result = harness.evaluate(tool_calls=calls, summary=answer)

    assert result.passed, (
        f"Task '{result.task}' failed: "
        f"{result.matched_actions}/{result.total_actions} actions matched. "
        f"Missing: {result.missing_actions}. "
        f"Actual tool calls: {result.actual_tool_calls}"
    )


def test_all_tasks_parse():
    """Every .yml in tasks/ must parse as a valid EvalHarness."""
    for h in discover_tasks():
        assert h.service, f"{h.name}: no service"
        if h.kind == "remediation":
            assert h.expected_remediation_container(), f"{h.name}: no expected_remediation_container"
            assert h.diagnosis(), f"{h.name}: no diagnosis"
        else:
            assert len(h.expected_actions()) > 0, f"{h.name}: no expected_agent_actions"


def test_validate_reference_all_tasks_pass_their_own_graders():
    """Every task's reference solution must pass its own graders.

    A failure here means the task is broken: its graders are stricter than its
    own reference solution (expected_evidence not in reference_summary,
    expected_source not in reference_tool_calls, etc.).
    """
    failures = []
    for h in discover_tasks():
        if not h.reference_summary() and not h.reference_tool_calls() and h.kind != "remediation":
            continue  # no reference declared (optional)
        res = h.validate_reference()
        if not res.passed:
            bad = [g.name for g in res.graders if not g.passed]
            failures.append(f"{h.name}: {bad}")
    assert not failures, "tasks whose own reference solution fails:\n  " + "\n  ".join(failures)


def test_api_down_task_calls_docker_status(tmp_database, patched_sources, monkeypatch):
    """Verify the 'api_down' task triggers docker_status specifically."""
    tools = _TASK_TOOL_CALLS["api_down"]
    answer = EvalHarness("api_down").reference_summary()
    responses = [FakeMessage(content="", tool_calls=tools), FakeMessage(content=answer)]

    from agent.config.settings import Settings

    monkeypatch.setattr(incident_module, "settings", Settings(max_tool_steps=6, _env_file=None))

    with patch("agent.workflows.incident.get_llm", return_value=FakeLLM(responses)):
        calls = asyncio.run(_run_task("api", tools, answer))

    harness = EvalHarness("api_down")
    result = harness.evaluate(tool_calls=calls, summary=answer)

    assert result.passed
    assert "docker_status" in result.actual_tool_calls
    assert result.score >= 0.7


def test_scrape_target_down_task_calls_query_prometheus(tmp_database, patched_sources, monkeypatch):
    """The scrape_target_down task should query Prometheus for scrape state."""
    tools = _TASK_TOOL_CALLS["scrape_target_down"]
    answer = EvalHarness("scrape_target_down").reference_summary()
    responses = [FakeMessage(content="", tool_calls=tools), FakeMessage(content=answer)]

    from agent.config.settings import Settings

    monkeypatch.setattr(incident_module, "settings", Settings(max_tool_steps=6, _env_file=None))

    with patch("agent.workflows.incident.get_llm", return_value=FakeLLM(responses)):
        calls = asyncio.run(_run_task("node-exporter", tools, answer))

    harness = EvalHarness("scrape_target_down")
    result = harness.evaluate(tool_calls=calls, summary=answer)

    assert result.passed
    assert "query_prometheus" in result.actual_tool_calls


def test_eval_cli_writes_transcripts_and_trials_log(tmp_path, monkeypatch):
    """`python -m agent eval` must save a per-trial transcript and append a row to trials.jsonl."""
    import json

    from agent.cli import main
    from agent.workflows import incident as inc

    async def fake_stream(prompt, *, system_prompt=None, tools=None, kind="ask", history=None):
        yield {"type": "tool_call", "step": 0, "name": "list_services", "args": {}}
        yield {"type": "tool_call", "step": 0, "name": "docker_status", "args": {"container": "vllm"}}
        yield {"type": "tool_call", "step": 0, "name": "docker_logs", "args": {"container": "vllm", "tail": 50}}
        yield {"type": "tool_result", "step": 0, "name": "docker_logs", "result": "vllm unreachable: connection refused"}
        yield {"type": "done", "content": "The local vLLM endpoint is unreachable."}

    monkeypatch.setattr(inc, "run_agentic_investigation_stream", fake_stream)

    out_dir = tmp_path / "eval_runs"
    rc = main(["eval", "--task", "vllm_down", "--out-dir", str(out_dir)])
    assert rc is None  # success

    trials_jsonl = out_dir / "trials.jsonl"
    assert trials_jsonl.exists(), "trials.jsonl not written"
    rows = [json.loads(line) for line in trials_jsonl.read_text().splitlines() if line.strip()]
    assert len(rows) == 1
    row = rows[0]
    assert row["task"] == "vllm_down"
    assert row["passed"] is True
    assert row["score"] == 1.0
    assert row["n_tool_calls"] == 3
    assert "duration_s" in row
    assert row["transcript_file"].endswith(".json")
    # grader breakdown is recorded per trial
    assert "graders" in row and row["graders"]["tool_calls"] is True

    run_dirs = [p for p in out_dir.iterdir() if p.is_dir()]
    assert len(run_dirs) == 1, "expected one run directory"
    trial_json = run_dirs[0] / "vllm_down__trial0.json"
    assert trial_json.exists(), "per-trial transcript not written"
    data = json.loads(trial_json.read_text())
    assert data["passed"] is True
    assert data["final_summary"] == "The local vLLM endpoint is unreachable."
    assert len(data["transcript"]) == 5
    assert data["transcript"][0]["name"] == "list_services"
    assert data["transcript"][-1]["type"] == "done"
    # the per-trial JSON carries the grader breakdown
    gnames = [g["name"] for g in data["graders"]]
    assert "tool_calls" in gnames and "groundedness" in gnames


def test_eval_cli_trials_writes_pass_at_k_summary(tmp_path, monkeypatch):
    """`--trials 3` writes 3 trial files, 3 trials.jsonl rows, and a __summary.json with pass@k/pass^k."""
    import json

    from agent.cli import main
    from agent.workflows import incident as inc

    # Alternating pass/fail: trials 0,2 pass (tool_result has evidence), trial 1 fails (no evidence in tool_result).
    trials = iter([
        ("vllm unreachable: connection refused", "The local vLLM endpoint is unreachable."),
        ("no useful info here", "Something is wrong."),  # tool_result lacks vllm+unreachable -> groundedness fails
        ("vllm unreachable: connection refused", "The local vLLM endpoint is unreachable."),
    ])

    async def fake_stream(prompt, *, system_prompt=None, tools=None, kind="ask", history=None):
        yield {"type": "tool_call", "step": 0, "name": "list_services", "args": {}}
        yield {"type": "tool_call", "step": 0, "name": "docker_status", "args": {"container": "vllm"}}
        yield {"type": "tool_call", "step": 0, "name": "docker_logs", "args": {"container": "vllm", "tail": 50}}
        result_text, summary_text = next(trials)
        yield {"type": "tool_result", "step": 0, "name": "docker_logs", "result": result_text}
        yield {"type": "done", "content": summary_text}

    monkeypatch.setattr(inc, "run_agentic_investigation_stream", fake_stream)

    out_dir = tmp_path / "eval_runs"
    # 2 of 3 trials pass -> pass@k=1, pass^k=0; CLI exits 1 because not all trials passed.
    with pytest.raises(SystemExit) as exc_info:
        main(["eval", "--task", "vllm_down", "--trials", "3", "--out-dir", str(out_dir)])
    assert exc_info.value.code == 1

    trials_jsonl = out_dir / "trials.jsonl"
    rows = [json.loads(line) for line in trials_jsonl.read_text().splitlines() if line.strip()]
    assert len(rows) == 3, "expected 3 trial rows"

    run_dir = next(p for p in out_dir.iterdir() if p.is_dir())
    for i in range(3):
        assert (run_dir / f"vllm_down__trial{i}.json").exists()
    summary = run_dir / "vllm_down__summary.json"
    assert summary.exists(), "__summary.json not written"
    s = json.loads(summary.read_text())
    assert s["n_trials"] == 3
    # 2 of 3 trials passed -> pass@k=1 (>=1 success), pass^k=0 (not all)
    assert s["pass_at_k"] == 1.0
    assert s["pass_k"] == 0.0
    assert s["wins"] == 2
    # groundedness grader passed in 2 of 3 trials
    assert s["graders"]["groundedness"] == 2 / 3


# --- grader unit tests ------------------------------------------------------

def _grader_named(result, name):
    return next(g for g in result.graders if g.name == name)


def test_groundedness_grader_passes_when_evidence_in_summary():
    h = EvalHarness("api_down")
    r = h.evaluate(tool_calls=["list_services", "docker_status", "docker_logs", "query_prometheus"],
                   summary="The api container is stopped.")
    g = _grader_named(r, "groundedness")
    assert g.passed, g.detail


def test_groundedness_grader_fails_when_evidence_missing():
    h = EvalHarness("api_down")  # expected_evidence: [api, stopped]
    r = h.evaluate(tool_calls=["list_services"], summary="Something is wrong with the web thing.")
    g = _grader_named(r, "groundedness")
    assert not g.passed
    assert "stopped" in g.detail


def test_no_false_alarm_grader_rejects_escalation_word():
    h = EvalHarness("healthy_service")  # kind: negative
    r = h.evaluate(tool_calls=["list_services", "docker_status"],
                   summary="The api container is down.")
    g = _grader_named(r, "no_false_alarm")
    assert not g.passed
    assert "down" in g.detail.lower()


def test_no_false_alarm_grader_passes_on_healthy_summary():
    h = EvalHarness("healthy_service")
    r = h.evaluate(tool_calls=["list_services", "docker_status"],
                   summary="The api container is running and healthy.")
    g = _grader_named(r, "no_false_alarm")
    assert g.passed, g.detail


def test_no_false_alarm_skipped_for_investigate_tasks():
    h = EvalHarness("api_down")  # kind: investigate (default)
    r = h.evaluate(tool_calls=["list_services", "docker_status", "docker_logs", "query_prometheus"],
                   summary="The api container is stopped.")
    g = _grader_named(r, "no_false_alarm")
    assert g.passed and g.detail.startswith("n/a")


def test_no_raw_markup_grader_rejects_dsml_and_tables():
    h = EvalHarness("api_down")
    dsml = "Result: \uFF5C\uFF5CDSML\uFF5C\uFF5Ctool_calls>...</>"
    r = h.evaluate(tool_calls=["list_services"], summary=dsml)
    assert not _grader_named(r, "no_raw_markup").passed
    table = "The service is down.\n| col | val |\n| a | b |"
    r2 = h.evaluate(tool_calls=["list_services"], summary=table)
    assert not _grader_named(r2, "no_raw_markup").passed


def test_no_raw_markup_grader_passes_clean_summary():
    h = EvalHarness("api_down")
    r = h.evaluate(tool_calls=["list_services", "docker_status", "docker_logs", "query_prometheus"],
                   summary="The api container is stopped; /health unreachable.")
    assert _grader_named(r, "no_raw_markup").passed


def test_aggregate_trials_pass_at_k_and_pass_k():
    from agent.eval import aggregate_trials

    class R:
        def __init__(self, passed, score=1.0):
            self.passed = passed
            self.score = score
            self.graders = [type("G", (), {"name": "tool_calls", "passed": passed})()]

    agg = aggregate_trials([R(True), R(False), R(True)])
    assert agg["k"] == 3
    assert agg["pass_at_k"] == 1.0   # at least one success
    assert agg["pass_k"] == 0.0      # not all succeeded
    assert agg["wins"] == 2

    agg2 = aggregate_trials([R(True), R(True)])
    assert agg2["pass_at_k"] == 1.0
    assert agg2["pass_k"] == 1.0      # all succeeded (consistency)


# --- Phase 1 grader tests: outcome + multi-turn ----------------------------

def test_groundedness_checks_tool_result_when_transcript_provided():
    """With a transcript, evidence must be in a tool_result event (grounded in observed data)."""
    import tempfile, yaml
    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as f:
        yaml.safe_dump({"name": "t", "service": "x", "expected_evidence": ["vllm", "down"]}, f)
        path = f.name
    h = EvalHarness(path)
    transcript = [
        {"type": "tool_call", "name": "docker_status"},
        {"type": "tool_result", "name": "docker_status", "result": "vllm is down"},
    ]
    r = h.evaluate(tool_calls=["docker_status"], summary="vllm is down.", transcript=transcript)
    assert _grader_named(r, "groundedness").passed  # both vllm + down in tool_result
    transcript2 = [{"type": "tool_result", "name": "docker_status", "result": "all good"}]
    r2 = h.evaluate(tool_calls=["docker_status"], summary="vllm is down.", transcript=transcript2)
    assert not _grader_named(r2, "groundedness").passed  # evidence not in tool_result, even though in summary


def test_groundedness_falls_back_to_summary_without_transcript():
    """Without a transcript, evidence is checked in the summary (backward compat)."""
    h = EvalHarness("api_down")
    r = h.evaluate(tool_calls=["list_services"], summary="The api container is stopped.")
    assert _grader_named(r, "groundedness").passed


def test_no_hallucination_grader_rejects_forbidden_container(tmp_path):
    import yaml
    p = tmp_path / "h.yml"
    p.write_text(yaml.safe_dump({
        "name": "h", "service": "x",
        "forbidden_containers": ["oracle-cloud-infrastructure"],
    }))
    h = EvalHarness(p)
    r = h.evaluate(tool_calls=["list_services"], summary="oracle-cloud-infrastructure is down")
    assert not _grader_named(r, "no_hallucination").passed
    r2 = h.evaluate(tool_calls=["list_services"], summary="api is healthy")
    assert _grader_named(r2, "no_hallucination").passed


def test_no_hallucination_skipped_without_forbidden_containers():
    h = EvalHarness("api_down")
    r = h.evaluate(tool_calls=["list_services"], summary="anything")
    g = _grader_named(r, "no_hallucination")
    assert g.passed and "no forbidden" in g.detail


def test_right_source_grader_loki(tmp_path):
    import yaml
    p = tmp_path / "l.yml"
    p.write_text(yaml.safe_dump({
        "name": "l", "service": "x", "kind": "logs", "expected_source": "loki",
        "expected_agent_actions": ["query loki for recent error logs"],
    }))
    h = EvalHarness(p)
    assert _grader_named(h.evaluate(tool_calls=["query_loki"], summary=""), "right_source").passed
    assert not _grader_named(h.evaluate(tool_calls=["docker_logs"], summary=""), "right_source").passed


def test_right_source_grader_docker_logs(tmp_path):
    import yaml
    p = tmp_path / "d.yml"
    p.write_text(yaml.safe_dump({
        "name": "d", "service": "x", "kind": "logs", "expected_source": "docker_logs",
    }))
    h = EvalHarness(p)
    assert _grader_named(h.evaluate(tool_calls=["docker_logs"], summary=""), "right_source").passed
    assert not _grader_named(h.evaluate(tool_calls=["query_loki"], summary=""), "right_source").passed


def test_right_source_skipped_for_non_logs_tasks():
    h = EvalHarness("api_down")  # kind defaults to investigate
    g = _grader_named(h.evaluate(tool_calls=[], summary=""), "right_source")
    assert g.passed and g.detail.startswith("n/a")


def test_right_metric_grader_latency(tmp_path):
    import yaml
    p = tmp_path / "pl.yml"
    p.write_text(yaml.safe_dump({
        "name": "pl", "service": "api", "kind": "perf", "expected_metric_family": "latency",
    }))
    h = EvalHarness(p)
    transcript = [{"type": "tool_call", "name": "query_prometheus", "args": {"promql": "histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))"}}]
    assert _grader_named(h.evaluate(tool_calls=["query_prometheus"], summary="", transcript=transcript), "right_metric").passed
    bad = [{"type": "tool_call", "name": "query_prometheus", "args": {"promql": "up{job='api'}"}}]
    assert not _grader_named(h.evaluate(tool_calls=["query_prometheus"], summary="", transcript=bad), "right_metric").passed


def test_right_metric_skipped_without_transcript(tmp_path):
    import yaml
    p = tmp_path / "pl2.yml"
    p.write_text(yaml.safe_dump({
        "name": "pl2", "service": "api", "kind": "perf", "expected_metric_family": "latency",
    }))
    h = EvalHarness(p)
    g = _grader_named(h.evaluate(tool_calls=["query_prometheus"], summary=""), "right_metric")
    assert g.passed and g.detail.startswith("n/a")


def test_right_metric_skipped_for_non_perf_tasks():
    h = EvalHarness("api_down")  # investigate
    g = _grader_named(h.evaluate(tool_calls=[], summary="", transcript=[]), "right_metric")
    assert g.passed and g.detail.startswith("n/a")


def test_history_property_loads_from_yaml(tmp_path):
    import yaml
    p = tmp_path / "m.yml"
    p.write_text(yaml.safe_dump({
        "name": "m", "service": "api",
        "history": [{"role": "user", "content": "what about the web thing?"}],
    }))
    h = EvalHarness(p)
    assert h.history() == [{"role": "user", "content": "what about the web thing?"}]


def test_history_is_passed_to_investigation_stream(tmp_path, monkeypatch):
    """The CLI must thread task `history:` into run_agentic_investigation_stream."""
    import yaml
    from agent.cli import main
    from agent.workflows import incident as inc

    captured = {}
    p = tmp_path / "mt.yml"
    p.write_text(yaml.safe_dump({
        "name": "mt", "service": "api",
        "history": [{"role": "user", "content": "earlier turn about n8n"}],
    }))

    async def fake_stream(prompt, *, system_prompt=None, tools=None, kind="ask", history=None):
        captured["history"] = history
        captured["prompt"] = prompt
        yield {"type": "done", "content": "ok"}

    monkeypatch.setattr(inc, "run_agentic_investigation_stream", fake_stream)
    out = tmp_path / "out"
    try:
        main(["eval", "--task", str(p), "--out-dir", str(out)])
    except SystemExit:
        pass
    assert captured["history"] == [{"role": "user", "content": "earlier turn about n8n"}]
    assert "api" in captured["prompt"]


# --- T13: remediation eval (outcome: which container proposed) --------------

def test_right_container_grader(tmp_path):
    import yaml
    p = tmp_path / "r.yml"
    p.write_text(yaml.safe_dump({
        "name": "r", "service": "api", "kind": "remediation",
        "expected_remediation_container": "marconi-agent-api",
    }))
    h = EvalHarness(p)
    good = [{"container_name": "marconi-agent-api"}]
    assert _grader_named(h.evaluate(tool_calls=[], summary="", proposals=good), "right_container").passed
    bad = [{"container_name": "marconi-agent-n8n"}]
    assert not _grader_named(h.evaluate(tool_calls=[], summary="", proposals=bad), "right_container").passed
    assert not _grader_named(h.evaluate(tool_calls=[], summary="", proposals=[]), "right_container").passed


def test_exactly_one_grader(tmp_path):
    import yaml
    p = tmp_path / "r2.yml"
    p.write_text(yaml.safe_dump({"name": "r2", "service": "api", "kind": "remediation"}))
    h = EvalHarness(p)
    assert _grader_named(h.evaluate(tool_calls=[], summary="", proposals=[{"x": 1}]), "exactly_one").passed
    assert not _grader_named(h.evaluate(tool_calls=[], summary="", proposals=[{"x": 1}, {"x": 2}]), "exactly_one").passed
    assert not _grader_named(h.evaluate(tool_calls=[], summary="", proposals=[]), "exactly_one").passed


def test_remediation_graders_skipped_for_non_remediation():
    h = EvalHarness("api_down")
    r = h.evaluate(tool_calls=[], summary="")
    assert _grader_named(r, "right_container").passed
    assert _grader_named(r, "exactly_one").passed


def test_eval_cli_remediation_drives_remediation_workflow(tmp_path, monkeypatch):
    """`python -m agent eval --task <remediation>` drives run_remediation_workflow, not the incident stream."""
    import yaml
    from agent.cli import main
    from agent.workflows import remediation as rem
    from agent.workflows import incident as inc

    incident_called = {"n": 0}
    captured = {}

    async def fake_remediation(incident_id, *, service, diagnosis):
        captured["incident_id"] = incident_id
        captured["service"] = service
        captured["diagnosis"] = diagnosis
        return {"summary": "Proposed restart of marconi-agent-api.", "proposals": [{"container_name": "marconi-agent-api"}]}

    async def fake_stream(prompt, *, system_prompt=None, tools=None, kind="ask", history=None):
        incident_called["n"] += 1
        yield {"type": "done", "content": "should not run"}

    monkeypatch.setattr(rem, "run_remediation_workflow", fake_remediation)
    monkeypatch.setattr(inc, "run_agentic_investigation_stream", fake_stream)

    p = tmp_path / "rem.yml"
    p.write_text(yaml.safe_dump({
        "name": "rem", "service": "api", "kind": "remediation",
        "diagnosis": "api container is stopped",
        "expected_remediation_container": "marconi-agent-api",
    }))
    out = tmp_path / "out"
    try:
        main(["eval", "--task", str(p), "--out-dir", str(out)])
    except SystemExit:
        pass
    assert incident_called["n"] == 0, "remediation task must not drive the incident stream"
    assert captured["service"] == "api"
    assert "api" in captured["diagnosis"]
