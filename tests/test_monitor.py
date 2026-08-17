"""Tests for the background container monitor."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.bot import monitor
from agent.config.settings import Settings


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
        {"Names": ["/marconi-agent-db"], "State": "running", "Status": "Up 1 hour"},
        {"Names": ["/extra-app"], "State": "running", "Status": "Up 1 hour"},  # watched, not filtered
        {"Names": ["/untracked-sidecar"], "State": "exited", "Status": "Exited"},  # neither
    ]
    monkeypatch.setattr(monitor.docker, "list_containers", AsyncMock(return_value=containers))
    monkeypatch.setattr(monitor.discord_alert, "send_alert", AsyncMock())

    asyncio.run(monitor._poll_containers(MagicMock()))
    assert "untracked-sidecar" not in monitor._container_state
    assert monitor._container_state == {
        "marconi-agent-api": "running",
        "marconi-agent-db": "running",
        "extra-app": "running",
    }

    # A tracked (filtered) container stops -> alert fires once.
    stopped = [
        {"Names": ["/marconi-agent-api"], "State": "exited", "Status": "Exited"},
        {"Names": ["/marconi-agent-db"], "State": "running", "Status": "Up 1 hour"},
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


@pytest.mark.integration
def test_demo_incident_scenario_end_to_end(monkeypatch):
    """The scripted demo from docs/demo.md, driven with fake Docker responses:
    loki running (baseline) -> stopped (critical alert to #alerts) ->
    running again (recovery note to #status-updates).
    """
    settings = Settings(
        docker_monitor=True,
        discord_alert_channel_id=1,
        discord_status_channel_id=2,
        _env_file=None,
    )
    monkeypatch.setattr(monitor, "settings", settings)
    monkeypatch.setattr(monitor, "list_watched_containers", list)
    monitor._container_state.clear()
    send_alert = AsyncMock()
    monkeypatch.setattr(monitor.discord_alert, "send_alert", send_alert)
    bot = MagicMock()

    running = [{"Names": ["/marconi-agent-loki"], "State": "running", "Status": "Up 2h"}]
    stopped = [{"Names": ["/marconi-agent-loki"], "State": "exited", "Status": "Exited (1)"}]

    # 1. Baseline poll: no alert.
    monkeypatch.setattr(monitor.docker, "list_containers", AsyncMock(return_value=running))
    asyncio.run(monitor._poll_containers(bot))
    send_alert.assert_not_awaited()

    # 2. `docker stop marconi-agent-loki` -> critical alert to #alerts.
    monkeypatch.setattr(monitor.docker, "list_containers", AsyncMock(return_value=stopped))
    asyncio.run(monitor._poll_containers(bot))
    send_alert.assert_awaited_once()
    args, kwargs = send_alert.await_args
    assert args[0] == 1
    assert kwargs["severity"] == "critical"
    assert "marconi-agent-loki" in args[1]

    # 3. `docker start marconi-agent-loki` -> recovery note to #status-updates.
    send_alert.reset_mock()
    monkeypatch.setattr(monitor.docker, "list_containers", AsyncMock(return_value=running))
    asyncio.run(monitor._poll_containers(bot))
    send_alert.assert_awaited_once()
    args, kwargs = send_alert.await_args
    assert args[0] == 2
    assert kwargs["severity"] == "info"
    assert "marconi-agent-loki" in args[1]


def _endpoint_settings():
    return Settings(
        monitored_endpoints="loki=http://localhost:3100/ready",
        discord_alert_channel_id=1,
        discord_status_channel_id=2,
        _env_file=None,
    )


def test_poll_endpoints_alerts_on_down_then_recovery(monkeypatch):
    """Baseline poll is silent; unreachable -> critical, reachable again -> info."""
    monkeypatch.setattr(monitor, "settings", _endpoint_settings())
    monkeypatch.setattr(monitor, "_endpoint_state", {})
    send_alert = AsyncMock()
    monkeypatch.setattr(monitor.discord_alert, "send_alert", send_alert)
    bot = MagicMock()

    # 1. First observation only baselines.
    monkeypatch.setattr(monitor, "_probe", AsyncMock(return_value=True))
    asyncio.run(monitor._poll_endpoints(bot))
    send_alert.assert_not_awaited()

    # 2. Endpoint stops answering -> critical alert to #alerts.
    monkeypatch.setattr(monitor, "_probe", AsyncMock(return_value=False))
    asyncio.run(monitor._poll_endpoints(bot))
    send_alert.assert_awaited_once()
    args, kwargs = send_alert.await_args
    assert args[0] == 1
    assert kwargs["severity"] == "critical"
    assert "loki" in args[1]

    # 3. Endpoint answers again -> recovery note to #status-updates.
    send_alert.reset_mock()
    monkeypatch.setattr(monitor, "_probe", AsyncMock(return_value=True))
    asyncio.run(monitor._poll_endpoints(bot))
    send_alert.assert_awaited_once()
    args, kwargs = send_alert.await_args
    assert args[0] == 2
    assert kwargs["severity"] == "info"

    # 4. Still up -> no repeat alert.
    send_alert.reset_mock()
    asyncio.run(monitor._poll_endpoints(bot))
    send_alert.assert_not_awaited()


def test_poll_endpoints_prunes_removed_endpoints(monkeypatch):
    monkeypatch.setattr(monitor, "settings", Settings(monitored_endpoints="", _env_file=None))
    monkeypatch.setattr(monitor, "_endpoint_state", {"gone": True})
    asyncio.run(monitor._poll_endpoints(MagicMock()))
    assert monitor._endpoint_state == {}


def test_probe_treats_error_status_and_exceptions_as_down(monkeypatch):
    """A 5xx/4xx or a connection failure both mean 'down', never an exception."""
    class FakeResponse:
        def __init__(self, code):
            self.status_code = code
            self.is_server_error = code >= 500

    class FakeClient:
        def __init__(self, response=None, exc=None):
            self._response, self._exc = response, exc
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def get(self, _url):
            if self._exc:
                raise self._exc
            return self._response

    for code, expected in ((200, True), (301, True), (404, False), (503, False)):
        monkeypatch.setattr(
            monitor.httpx, "AsyncClient", lambda *a, _c=code, **kw: FakeClient(FakeResponse(_c))
        )
        assert asyncio.run(monitor._probe("http://x")) is expected

    monkeypatch.setattr(
        monitor.httpx, "AsyncClient",
        lambda *a, **kw: FakeClient(exc=monitor.httpx.ConnectError("refused")),
    )
    assert asyncio.run(monitor._probe("http://x")) is False
