"""Tests for the background Discord endpoint monitor."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.bot import monitor
from agent.config.settings import Settings
from agent.helpers.sources import loki, prometheus


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


def test_poll_containers_alerts_on_filtered_container_stopping(monkeypatch):
    """A container matching docker_name_filter transitioning running -> stopped
    sends a critical alert. This is the 'prometheus went down' case: alerting
    is Docker-only, so no PromQL scrape gap can mis-fire.
    """
    settings = Settings(
        docker_monitor=True,
        docker_name_filter="marconi-",
        discord_alert_channel_id=1,
        discord_status_channel_id=2,
        _env_file=None,
    )
    monkeypatch.setattr(monitor, "settings", settings)
    monkeypatch.setattr(monitor, "list_watched_containers", lambda: [])
    monitor._container_state.clear()

    bot = MagicMock()
    running = [{"Names": ["/marconi-agent-prometheus"], "State": "running", "Status": "Up 1h"}]
    monkeypatch.setattr(monitor.docker, "list_containers", AsyncMock(return_value=running))
    monkeypatch.setattr(monitor.discord_alert, "send_alert", AsyncMock())

    asyncio.run(monitor._poll_containers(bot))  # baseline: running, no alert
    monitor.discord_alert.send_alert.assert_not_awaited()

    stopped = [{"Names": ["/marconi-agent-prometheus"], "State": "exited", "Status": "Exited"}]
    monkeypatch.setattr(monitor.docker, "list_containers", AsyncMock(return_value=stopped))
    asyncio.run(monitor._poll_containers(bot))  # running -> stopped: alert
    monitor.discord_alert.send_alert.assert_awaited_once()


def test_poll_containers_no_alert_on_first_poll_after_restart(monkeypatch):
    """The first poll after a monitor restart baselines current state (prev is
    None), so a container that is ALREADY down when the monitor starts produces
    no false edge. This is what was broken with the PromQL path on restart.
    """
    settings = Settings(docker_monitor=True, discord_alert_channel_id=1, _env_file=None)
    monkeypatch.setattr(monitor, "settings", settings)
    monkeypatch.setattr(monitor, "list_watched_containers", lambda: [])
    monitor._container_state.clear()

    already_down = [{"Names": ["/marconi-agent-prometheus"], "State": "exited", "Status": "Exited"}]
    monkeypatch.setattr(monitor.docker, "list_containers", AsyncMock(return_value=already_down))
    monkeypatch.setattr(monitor.discord_alert, "send_alert", AsyncMock())

    asyncio.run(monitor._poll_containers(MagicMock()))
    monitor.discord_alert.send_alert.assert_not_awaited()  # baseline, no false edge


def test_poll_containers_recovery_alert_to_status_channel(monkeypatch):
    """A not-running -> running transition posts a recovery note to #status-updates."""
    settings = Settings(
        docker_monitor=True, docker_name_filter="marconi-",
        discord_alert_channel_id=1, discord_status_channel_id=2, _env_file=None,
    )
    monkeypatch.setattr(monitor, "settings", settings)
    monkeypatch.setattr(monitor, "list_watched_containers", lambda: [])
    monitor._container_state.clear()
    monitor._container_state["marconi-agent-api"] = "exited"

    bot = MagicMock()
    back_up = [{"Names": ["/marconi-agent-api"], "State": "running", "Status": "Up"}]
    monkeypatch.setattr(monitor.docker, "list_containers", AsyncMock(return_value=back_up))
    send_alert = AsyncMock()
    monkeypatch.setattr(monitor.discord_alert, "send_alert", send_alert)

    asyncio.run(monitor._poll_containers(bot))
    send_alert.assert_awaited_once()
    # recovery goes to the status channel (id 2), not the alert channel (id 1)
    assert send_alert.await_args.args[0] == 2


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


def test_query_loki_uses_range_endpoint_not_instant():
    """Regression: Loki's instant /query endpoint rejects plain log-stream
    selectors ("log queries are not supported as an instant query type"), so
    query_loki must delegate to /query_range, not /query."""
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"status": "success"}

    fake_client = MagicMock()
    fake_client.get = AsyncMock(return_value=FakeResponse())
    fake_cm = MagicMock()
    fake_cm.__aenter__ = AsyncMock(return_value=fake_client)
    fake_cm.__aexit__ = AsyncMock(return_value=False)

    with patch.object(loki.httpx, "AsyncClient", return_value=fake_cm):
        asyncio.run(loki.query_loki('{container="x"}'))

    url = fake_client.get.call_args.args[0]
    assert url.endswith("/loki/api/v1/query_range")
    assert "start" in fake_client.get.call_args.kwargs["params"]


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


def test_poll_containers_tracks_filtered_and_watched(monkeypatch):
    """Tracked = containers matching docker_name_filter ∪ explicitly watched.
    With a name_filter set, an out-of-filter container is tracked only if watched.
    """
    settings = Settings(
        docker_monitor=True,
        docker_name_filter="marconi-",
        discord_alert_channel_id=2,
        discord_status_channel_id=3,
        _env_file=None,
    )
    monkeypatch.setattr(monitor, "settings", settings)
    monkeypatch.setattr(monitor, "list_watched_containers", lambda: ["extra-app"])
    monitor._container_state.clear()

    containers = [
        {"Names": ["/marconi-agent-api"], "State": "running", "Status": "Up 1 hour"},
        {"Names": ["/marconi-agent-n8n"], "State": "running", "Status": "Up 1 hour"},
        {"Names": ["/extra-app"], "State": "running", "Status": "Up 1 hour"},  # watched, not filtered
        {"Names": ["/untracked-sidecar"], "State": "exited", "Status": "Exited"},  # neither
    ]
    monkeypatch.setattr(monitor.docker, "list_containers", AsyncMock(return_value=containers))
    monkeypatch.setattr(monitor.discord_alert, "send_alert", AsyncMock())

    asyncio.run(monitor._poll_containers(MagicMock()))
    assert "untracked-sidecar" not in monitor._container_state
    assert monitor._container_state == {
        "marconi-agent-api": "running",
        "marconi-agent-n8n": "running",
        "extra-app": "running",
    }

    # A tracked (filtered) container stops -> alert fires once.
    stopped = [
        {"Names": ["/marconi-agent-api"], "State": "exited", "Status": "Exited"},
        {"Names": ["/marconi-agent-n8n"], "State": "running", "Status": "Up 1 hour"},
        {"Names": ["/extra-app"], "State": "running", "Status": "Up 1 hour"},
    ]
    monkeypatch.setattr(monitor.docker, "list_containers", AsyncMock(return_value=stopped))
    send_alert = AsyncMock()
    monkeypatch.setattr(monitor.discord_alert, "send_alert", send_alert)
    asyncio.run(monitor._poll_containers(MagicMock()))
    send_alert.assert_awaited_once()
    assert "marconi-agent-api" in send_alert.await_args.args[1]


def test_poll_containers_empty_filter_tracks_all(monkeypatch):
    """With docker_name_filter empty, every container is in scope (watched is a
    no-op superset). This is the default deployment shape.
    """
    settings = Settings(docker_monitor=True, docker_name_filter="", _env_file=None)
    monkeypatch.setattr(monitor, "settings", settings)
    monkeypatch.setattr(monitor, "list_watched_containers", lambda: [])
    monitor._container_state.clear()
    containers = [
        {"Names": ["/vllm"], "State": "running", "Status": "Up"},
        {"Names": ["/cadvisor"], "State": "running", "Status": "Up"},
    ]
    monkeypatch.setattr(monitor.docker, "list_containers", AsyncMock(return_value=containers))
    asyncio.run(monitor._poll_containers(MagicMock()))
    assert monitor._container_state == {"vllm": "running", "cadvisor": "running"}


def test_poll_containers_prunes_out_of_scope_state(monkeypatch):
    settings = Settings(
        docker_monitor=True,
        docker_name_filter="marconi-",
        discord_alert_channel_id=2,
        _env_file=None,
    )
    monkeypatch.setattr(monitor, "settings", settings)
    monkeypatch.setattr(monitor, "list_watched_containers", lambda: [])
    monitor._container_state.clear()
    monitor._container_state.update({"marconi-agent-api": "running", "old": "running"})

    containers = [{"Names": ["/marconi-agent-api"], "State": "running", "Status": "Up 1 hour"}]
    monkeypatch.setattr(monitor.docker, "list_containers", AsyncMock(return_value=containers))
    monkeypatch.setattr(monitor.discord_alert, "send_alert", AsyncMock())

    asyncio.run(monitor._poll_containers(MagicMock()))
    assert "old" not in monitor._container_state
    assert monitor._container_state == {"marconi-agent-api": "running"}
