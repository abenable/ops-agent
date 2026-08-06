"""Tests for the background Discord endpoint monitor."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.bot import monitor
from agent.config.settings import Settings
from agent.tools.sources import loki, prometheus


@pytest.fixture
def sample_settings():
    return Settings(
        monitored_endpoints="api=http://localhost:8000, db=http://localhost:5432",
        monitor_interval_seconds=60,
        _env_file=None,
    )


def test_endpoints_parsing(sample_settings, monkeypatch):
    monkeypatch.setattr(monitor, "settings", sample_settings)
    endpoints = monitor._endpoints()
    assert endpoints == {
        "api": "http://localhost:8000",
        "db": "http://localhost:5432",
    }


def test_endpoints_ignores_empty_items(monkeypatch):
    monkeypatch.setattr(
        monitor,
        "settings",
        Settings(monitored_endpoints="api=http://x,,=bad,no-equals", _env_file=None),
    )
    assert monitor._endpoints() == {"api": "http://x"}


def test_endpoints_empty_by_default(monkeypatch):
    # load_env() pushes .env into os.environ, so clear the key to test the true default.
    monkeypatch.delenv("MONITORED_ENDPOINTS", raising=False)
    monkeypatch.setattr(monitor, "settings", Settings(_env_file=None))
    assert monitor._endpoints() == {}


def test_poll_once_escalates_on_healthy_to_down(monkeypatch):
    settings = Settings(
        monitored_endpoints="web=http://localhost:8000",
        discord_status_channel_id=1,
        discord_alert_channel_id=2,
        # Neutralize the other two poll phases so only endpoint logic is exercised.
        # Explicit kwargs override os.environ, which load_env() pollutes from .env.
        docker_monitor=False,
        prometheus_alert_rules="",
        _env_file=None,
    )
    monkeypatch.setattr(monitor, "settings", settings)
    monitor._last_state.clear()

    bot = MagicMock()
    send_alert = AsyncMock()
    monkeypatch.setattr(monitor.discord_alert, "send_alert", send_alert)
    run_workflow = AsyncMock(return_value={"incident_id": "abc123", "summary": "oh no"})
    monkeypatch.setattr(monitor, "run_incident_workflow", run_workflow)
    open_thread = AsyncMock()
    monkeypatch.setattr(monitor.discord_alert, "open_incident_thread", open_thread)

    # First poll: endpoint is up. No alerts because there is no previous state.
    monkeypatch.setattr(
        monitor, "check_endpoint", AsyncMock(return_value={"reachable": True, "status_code": 200})
    )
    asyncio.run(monitor._poll_once(bot))
    send_alert.assert_not_awaited()
    run_workflow.assert_not_awaited()

    # Second poll: endpoint goes down. Should post status-change + critical alert + incident.
    monkeypatch.setattr(
        monitor, "check_endpoint", AsyncMock(return_value={"reachable": False, "status_code": None})
    )
    asyncio.run(monitor._poll_once(bot))

    assert send_alert.await_count == 2
    assert send_alert.await_args.kwargs["severity"] == "critical"
    run_workflow.assert_awaited_once()
    open_thread.assert_awaited_once()


def test_alert_rules_parsing(monkeypatch):
    monkeypatch.setattr(
        monitor,
        "settings",
        Settings(prometheus_alert_rules="target_down=up == 0, high_load=node_load1 > 4", _env_file=None),
    )
    assert monitor._alert_rules() == {
        "target_down": "up == 0",
        "high_load": "node_load1 > 4",
    }


def test_alert_rules_empty_by_default(monkeypatch):
    monkeypatch.delenv("PROMETHEUS_ALERT_RULES", raising=False)
    monkeypatch.setattr(monitor, "settings", Settings(_env_file=None))
    assert monitor._alert_rules() == {}


def test_evaluate_rules_fires_once_on_edge_and_skips_empty(monkeypatch):
    settings = Settings(
        prometheus_alert_rules="target_down=up == 0",
        discord_alert_channel_id=1,
        _env_file=None,
    )
    monkeypatch.setattr(monitor, "settings", settings)
    monitor._rule_state.clear()

    bot = MagicMock()
    query_mock = AsyncMock(
        side_effect=[
            {"data": {"result": []}},
            {"data": {"result": [{"metric": {}}]}},
            {"data": {"result": [{"metric": {}}]}},
        ]
    )
    monkeypatch.setattr(monitor, "query_prometheus", query_mock)
    send_alert = AsyncMock()
    monkeypatch.setattr(monitor.discord_alert, "send_alert", send_alert)
    run_workflow = AsyncMock(return_value={"incident_id": "xyz", "summary": "bad"})
    monkeypatch.setattr(monitor, "run_incident_workflow", run_workflow)
    open_thread = AsyncMock()
    monkeypatch.setattr(monitor.discord_alert, "open_incident_thread", open_thread)

    # Empty result: no alert.
    asyncio.run(monitor._evaluate_rules(bot))
    send_alert.assert_not_awaited()
    run_workflow.assert_not_awaited()

    # Transition to firing: alert + incident thread exactly once.
    asyncio.run(monitor._evaluate_rules(bot))
    send_alert.assert_awaited_once()
    run_workflow.assert_awaited_once()
    open_thread.assert_awaited_once()

    # Still firing: no additional alert.
    asyncio.run(monitor._evaluate_rules(bot))
    assert send_alert.await_count == 1
    assert run_workflow.await_count == 1


def test_evaluate_rules_dispatches_investigation_with_detected_target_label(monkeypatch):
    """The monitor must pass the *detected* service/target label (not the opaque
    rule name) to run_incident_workflow, so the investigation targets the right
    container. This is the 'identify incidents' dispatch contract; the LLM
    investigation it triggers is graded by the api_down/root-cause evals.
    """
    settings = Settings(
        prometheus_alert_rules="target_down=up == 0",
        discord_alert_channel_id=1,
        _env_file=None,
    )
    monkeypatch.setattr(monitor, "settings", settings)
    monitor._rule_state.clear()

    bot = MagicMock()
    # Firing series carries job=node-exporter -> label "target_down: node-exporter"
    query_mock = AsyncMock(
        side_effect=[{"data": {"result": [{"metric": {"job": "node-exporter"}}]}}]
    )
    monkeypatch.setattr(monitor, "query_prometheus", query_mock)
    monkeypatch.setattr(monitor.discord_alert, "send_alert", AsyncMock())
    run_workflow = AsyncMock(return_value={"incident_id": "xyz", "summary": "bad"})
    monkeypatch.setattr(monitor, "run_incident_workflow", run_workflow)
    monkeypatch.setattr(monitor.discord_alert, "open_incident_thread", AsyncMock())

    asyncio.run(monitor._evaluate_rules(bot))
    # The dispatched investigation must target the detected service, not "target_down".
    run_workflow.assert_awaited_once()
    dispatched_label = run_workflow.await_args.args[0]
    assert "node-exporter" in dispatched_label, f"dispatched label was {dispatched_label!r}"


def _assert_source_client_headers(module, token_setting, monkeypatch):
    """Helper: assert the source client sends Bearer <token> when configured."""
    monkeypatch.setattr(module.settings, token_setting, "secret")
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {}

    fake_client = MagicMock()
    fake_client.get = AsyncMock(return_value=FakeResponse())

    fake_cm = MagicMock()
    fake_cm.__aenter__ = AsyncMock(return_value=fake_client)
    fake_cm.__aexit__ = AsyncMock(return_value=False)

    with patch.object(module.httpx, "AsyncClient", return_value=fake_cm) as Client:
        asyncio.run(module.query_prometheus("up") if hasattr(module, "query_prometheus") else module.query_loki("{app=\"x\"}"))
        captured["kwargs"] = Client.call_args.kwargs

    assert captured["kwargs"]["headers"] == {"Authorization": "Bearer secret"}


def test_prometheus_token_sent_when_set(monkeypatch):
    # Ensure no token leakage from global settings.
    monkeypatch.setattr(prometheus.settings, "prometheus_token", "")
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {}

    fake_client = MagicMock()
    fake_client.get = AsyncMock(return_value=FakeResponse())
    fake_cm = MagicMock()
    fake_cm.__aenter__ = AsyncMock(return_value=fake_client)
    fake_cm.__aexit__ = AsyncMock(return_value=False)

    with patch.object(prometheus.httpx, "AsyncClient", return_value=fake_cm) as Client:
        asyncio.run(prometheus.query_prometheus("up"))
        captured["kwargs"] = Client.call_args.kwargs

    assert captured["kwargs"]["timeout"] == 10.0
    assert captured["kwargs"]["headers"] == {}

    # Now with a token set.
    monkeypatch.setattr(prometheus.settings, "prometheus_token", "secret")
    with patch.object(prometheus.httpx, "AsyncClient", return_value=fake_cm) as Client:
        asyncio.run(prometheus.query_prometheus("up"))
        assert Client.call_args.kwargs["headers"] == {"Authorization": "Bearer secret"}


def test_loki_token_sent_when_set(monkeypatch):
    monkeypatch.setattr(loki.settings, "loki_token", "")
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {}

    fake_client = MagicMock()
    fake_client.get = AsyncMock(return_value=FakeResponse())
    fake_cm = MagicMock()
    fake_cm.__aenter__ = AsyncMock(return_value=fake_client)
    fake_cm.__aexit__ = AsyncMock(return_value=False)

    with patch.object(loki.httpx, "AsyncClient", return_value=fake_cm) as Client:
        asyncio.run(loki.query_loki('{app="x"}'))
        captured["kwargs"] = Client.call_args.kwargs

    assert captured["kwargs"]["timeout"] == 10.0
    assert captured["kwargs"]["headers"] == {}

    monkeypatch.setattr(loki.settings, "loki_token", "secret")
    with patch.object(loki.httpx, "AsyncClient", return_value=fake_cm) as Client:
        asyncio.run(loki.query_loki('{app="x"}'))
        assert Client.call_args.kwargs["headers"] == {"Authorization": "Bearer secret"}


def test_container_snapshot_posts_when_containers_watched(monkeypatch):
    settings = Settings(discord_status_channel_id=1)
    monkeypatch.setattr(monitor, "settings", settings)
    monitor._container_state.clear()
    monitor._container_state.update({"api": "running", "db": "exited"})

    bot = MagicMock()
    send_alert = AsyncMock()
    monkeypatch.setattr(monitor.discord_alert, "send_alert", send_alert)

    asyncio.run(monitor._post_container_snapshot(bot))

    send_alert.assert_awaited_once()
    desc = send_alert.await_args.args[1]
    assert "api" in desc and "running" in desc
    assert "db" in desc and "exited" in desc
    assert send_alert.await_args.kwargs["title"] == "Container status"


def test_container_snapshot_quiet_when_nothing_watched(monkeypatch):
    settings = Settings(discord_status_channel_id=1)
    monkeypatch.setattr(monitor, "settings", settings)
    monitor._container_state.clear()

    send_alert = AsyncMock()
    monkeypatch.setattr(monitor.discord_alert, "send_alert", send_alert)
    asyncio.run(monitor._post_container_snapshot(MagicMock()))
    send_alert.assert_not_awaited()


def test_container_snapshot_quiet_when_no_status_channel(monkeypatch):
    monkeypatch.delenv("DISCORD_STATUS_CHANNEL_ID", raising=False)
    monkeypatch.setattr(monitor, "settings", Settings(_env_file=None))
    monitor._container_state.clear()
    monitor._container_state.update({"api": "running"})

    send_alert = AsyncMock()
    monkeypatch.setattr(monitor.discord_alert, "send_alert", send_alert)
    asyncio.run(monitor._post_container_snapshot(MagicMock()))
    send_alert.assert_not_awaited()


def test_poll_containers_tracks_only_watched_containers(monkeypatch):
    settings = Settings(
        docker_monitor=True,
        discord_alert_channel_id=2,
        _env_file=None,
    )
    monkeypatch.setattr(monitor, "settings", settings)
    monkeypatch.setattr(
        monitor,
        "list_watched_containers",
        lambda: ["web", "db"],
    )
    monitor._container_state.clear()

    containers = [
        {"Names": ["/web"], "State": "running", "Status": "Up 1 hour"},
        {"Names": ["/db"], "State": "running", "Status": "Up 1 hour"},
        {"Names": ["/unwatched-sidecar"], "State": "exited", "Status": "Exited (1) 2 hours ago"},
    ]
    monkeypatch.setattr(monitor.docker, "list_containers", AsyncMock(return_value=containers))
    send_alert = AsyncMock()
    monkeypatch.setattr(monitor.discord_alert, "send_alert", send_alert)

    asyncio.run(monitor._poll_containers(MagicMock()))
    # Unwatched containers are ignored entirely.
    assert "unwatched-sidecar" not in monitor._container_state
    assert monitor._container_state == {"web": "running", "db": "running"}
    send_alert.assert_not_awaited()

    # A watched container stops -> alert fires once.
    monkeypatch.setattr(
        monitor.docker,
        "list_containers",
        AsyncMock(
            return_value=[
                {"Names": ["/web"], "State": "exited", "Status": "Exited (1) 1 min ago"},
                {"Names": ["/db"], "State": "running", "Status": "Up 1 hour"},
                {"Names": ["/unwatched-sidecar"], "State": "exited", "Status": "Exited (1) 2 hours ago"},
            ]
        ),
    )
    asyncio.run(monitor._poll_containers(MagicMock()))
    send_alert.assert_awaited_once()
    assert "web" in send_alert.await_args.args[1]


def test_poll_containers_prunes_unwatched_state(monkeypatch):
    settings = Settings(
        docker_monitor=True,
        discord_alert_channel_id=2,
        _env_file=None,
    )
    monkeypatch.setattr(monitor, "settings", settings)
    monkeypatch.setattr(monitor, "list_watched_containers", lambda: ["web"])
    monitor._container_state.clear()
    monitor._container_state.update({"web": "running", "old": "running"})

    containers = [{"Names": ["/web"], "State": "running", "Status": "Up 1 hour"}]
    monkeypatch.setattr(monitor.docker, "list_containers", AsyncMock(return_value=containers))
    send_alert = AsyncMock()
    monkeypatch.setattr(monitor.discord_alert, "send_alert", send_alert)

    asyncio.run(monitor._poll_containers(MagicMock()))
    assert "old" not in monitor._container_state
    assert monitor._container_state == {"web": "running"}
