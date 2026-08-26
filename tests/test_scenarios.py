"""Tests for the staged-scenario grader and the PromQL alert rules."""

import importlib.util
from pathlib import Path

import pytest

from agent.bot import monitor

_SPEC = importlib.util.spec_from_file_location(
    "run_scenario", Path(__file__).resolve().parents[1] / "scripts" / "run_scenario.py"
)
run_scenario = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(run_scenario)


@pytest.mark.parametrize(
    ("scenario", "answer", "expected"),
    [
        ("container_down", "The container has exited and is not running.", True),
        ("container_down", "It is running normally.", False),
        ("healthy", "The container is up and running.", True),
        # the control case: an agent that always cries "down" must fail here
        ("healthy", "It has exited.", False),
    ],
)
def test_grader_separates_a_real_diagnosis_from_a_reflex(scenario, answer, expected):
    spec = run_scenario.SCENARIOS[scenario]
    assert run_scenario._grade(answer, spec)["passed"] is expected


def test_healthy_scenario_rejects_down_words_even_alongside_up_words():
    """'running' appearing anywhere must not rescue an answer that says exited."""
    spec = run_scenario.SCENARIOS["healthy"]
    graded = run_scenario._grade("It was running, but it has exited.", spec)
    assert graded["passed"] is False
    assert graded["rejected"] == ["exited"]


def test_scenario_target_is_not_a_real_lab_container():
    assert run_scenario.TARGET.startswith("marconi-scenario-")


def test_alert_rules_split_on_the_first_equals_only(monkeypatch):
    """PromQL contains '=', so only the first one separates name from expression."""
    monkeypatch.setattr(
        monitor.settings, "prometheus_alert_rules",
        "target_down=up == 0,saturated=rate(cpu[5m]) > 0.9,bad,=noname,noexpr=",
    )
    assert monitor._alert_rules() == {
        "target_down": "up == 0",
        "saturated": "rate(cpu[5m]) > 0.9",
    }


def test_no_rules_configured_is_empty(monkeypatch):
    monkeypatch.setattr(monitor.settings, "prometheus_alert_rules", "")
    assert monitor._alert_rules() == {}


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"status": "success", "data": {"result": [{"metric": {}}]}}, True),
        ({"status": "success", "data": {"result": []}}, False),
        ({"status": "error", "error": "bad query"}, None),
        ({"status": "success"}, False),
    ],
)
def test_rule_firing_reads_the_prometheus_envelope(monkeypatch, payload, expected):
    async def _query(_promql):
        return payload

    monkeypatch.setattr(monitor.prometheus, "query", _query)
    import asyncio

    assert asyncio.run(monitor._rule_firing("up == 0")) is expected


def test_rule_firing_is_none_when_prometheus_is_unreachable(monkeypatch):
    async def _query(_promql):
        raise OSError("connection refused")

    monkeypatch.setattr(monitor.prometheus, "query", _query)
    import asyncio

    assert asyncio.run(monitor._rule_firing("up == 0")) is None


def test_firing_rule_does_not_block_the_poll_loop(monkeypatch):
    """A slow investigation must not delay the next container/endpoint check."""
    import asyncio

    monkeypatch.setattr(monitor.settings, "prometheus_url", "http://prom")
    monkeypatch.setattr(monitor.settings, "prometheus_alert_rules", "down=up == 0")
    monkeypatch.setattr(monitor.settings, "discord_alert_channel_id", 1)
    monkeypatch.setattr(monitor.settings, "discord_incident_channel_id", 2)
    monkeypatch.setattr(monitor, "_rule_state", {"down": False})

    async def _query(_promql):
        return {"status": "success", "data": {"result": [{"metric": {}}]}}

    sent = []

    async def _send(*args, **kwargs):
        sent.append(kwargs.get("title"))

    started = asyncio.Event()

    async def _slow_incident(*_args):
        started.set()
        await asyncio.sleep(30)

    monkeypatch.setattr(monitor.prometheus, "query", _query)
    monkeypatch.setattr(monitor.discord_alert, "send_alert", _send)
    monkeypatch.setattr(monitor, "_open_incident", _slow_incident)

    async def run():
        await asyncio.wait_for(monitor._poll_alert_rules(None), timeout=2)
        await asyncio.wait_for(started.wait(), timeout=2)
        for task in list(monitor._incident_tasks):
            task.cancel()

    asyncio.run(run())
    assert sent == ["Alert rule firing"]


def test_a_failed_query_never_reads_as_resolved(monkeypatch):
    """Unreachable Prometheus must not turn a firing rule into a recovery notice."""
    import asyncio

    monkeypatch.setattr(monitor.settings, "prometheus_url", "http://prom")
    monkeypatch.setattr(monitor.settings, "prometheus_alert_rules", "down=up == 0")
    monkeypatch.setattr(monitor.settings, "discord_status_channel_id", 1)
    monkeypatch.setattr(monitor, "_rule_state", {"down": True})

    async def _query(_promql):
        raise OSError("connection refused")

    sent = []
    monkeypatch.setattr(monitor.prometheus, "query", _query)
    monkeypatch.setattr(monitor.discord_alert, "send_alert", lambda *a, **k: sent.append(k))

    asyncio.run(monitor._poll_alert_rules(None))

    assert sent == []
    assert monitor._rule_state["down"] is True
