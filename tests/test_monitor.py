"""Tests for the background container monitor."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.bot import monitor
from agent.config.settings import Settings


def _settings(**kw):
    """A Settings isolated from the ambient environment."""
    return Settings(_env_file=None, **kw)


def _use_settings(monkeypatch, **kw):
    monkeypatch.setattr(monitor, "settings", _settings(**kw))


def test_endpoints_parsing(monkeypatch):
    """Pairs are split on '=', blanks and malformed items dropped, empty by default."""
    _use_settings(monkeypatch, monitored_endpoints="api=http://localhost:8000, db=http://localhost:5432")
    assert monitor._endpoints() == {
        "api": "http://localhost:8000",
        "db": "http://localhost:5432",
    }

    _use_settings(monkeypatch, monitored_endpoints="api=http://x,,=bad,no-equals")
    assert monitor._endpoints() == {"api": "http://x"}

    monkeypatch.delenv("MONITORED_ENDPOINTS", raising=False)
    _use_settings(monkeypatch)
    assert monitor._endpoints() == {}


def test_poll_containers_alerts_on_filtered_container_stopping(monkeypatch):
    """A container matching docker_name_filter transitioning running -> stopped sends a critical alert."""
    _use_settings(
        monkeypatch,
        docker_monitor=True,
        docker_name_filter="marconi-",
        discord_alert_channel_id=1,
        discord_status_channel_id=2,
    )
    monkeypatch.setattr(monitor, "list_watched_containers", list)
    monitor._container_state.clear()

    bot = MagicMock()
    running = [{"Names": ["/marconi-agent-prometheus"], "State": "running", "Status": "Up 1h"}]
    monkeypatch.setattr(monitor.docker, "list_containers", AsyncMock(return_value=running))
    monkeypatch.setattr(monitor.discord_alert, "send_alert", AsyncMock())

    asyncio.run(monitor._poll_containers(bot))
    monitor.discord_alert.send_alert.assert_not_awaited()

    stopped = [{"Names": ["/marconi-agent-prometheus"], "State": "exited", "Status": "Exited"}]
    monkeypatch.setattr(monitor.docker, "list_containers", AsyncMock(return_value=stopped))
    asyncio.run(monitor._poll_containers(bot))
    monitor.discord_alert.send_alert.assert_awaited_once()
    args, kwargs = monitor.discord_alert.send_alert.await_args
    assert args[0] == 1
    assert kwargs["severity"] == "critical"
    assert "marconi-agent-prometheus" in args[1]


def test_poll_containers_no_alert_on_first_poll_after_restart(monkeypatch):
    """The first poll after a monitor restart baselines current state, producing no false edge."""
    _use_settings(monkeypatch, docker_monitor=True, discord_alert_channel_id=1)
    monkeypatch.setattr(monitor, "list_watched_containers", list)
    monitor._container_state.clear()

    already_down = [{"Names": ["/marconi-agent-prometheus"], "State": "exited", "Status": "Exited"}]
    monkeypatch.setattr(monitor.docker, "list_containers", AsyncMock(return_value=already_down))
    monkeypatch.setattr(monitor.discord_alert, "send_alert", AsyncMock())

    asyncio.run(monitor._poll_containers(MagicMock()))
    monitor.discord_alert.send_alert.assert_not_awaited()


def test_poll_containers_recovery_alert_to_status_channel(monkeypatch):
    """A not-running -> running transition posts a recovery note to #status-updates."""
    _use_settings(
        monkeypatch, docker_monitor=True, docker_name_filter="marconi-",
        discord_alert_channel_id=1, discord_status_channel_id=2,
    )
    monkeypatch.setattr(monitor, "list_watched_containers", list)
    monitor._container_state.clear()
    monitor._container_state["marconi-agent-api"] = "exited"

    bot = MagicMock()
    back_up = [{"Names": ["/marconi-agent-api"], "State": "running", "Status": "Up"}]
    monkeypatch.setattr(monitor.docker, "list_containers", AsyncMock(return_value=back_up))
    send_alert = AsyncMock()
    monkeypatch.setattr(monitor.discord_alert, "send_alert", send_alert)

    asyncio.run(monitor._poll_containers(bot))
    send_alert.assert_awaited_once()
    args, kwargs = send_alert.await_args
    assert args[0] == 2
    assert kwargs["severity"] == "info"
    assert "marconi-agent-api" in args[1]


def test_poll_containers_tracks_filtered_and_watched(monkeypatch):
    """Tracked = containers matching docker_name_filter ∪ explicitly watched."""
    _use_settings(
        monkeypatch,
        docker_monitor=True,
        docker_name_filter="marconi-",
        discord_alert_channel_id=2,
        discord_status_channel_id=3,
    )
    monkeypatch.setattr(monitor, "list_watched_containers", lambda: ["extra-app"])
    monitor._container_state.clear()

    containers = [
        {"Names": ["/marconi-agent-api"], "State": "running", "Status": "Up 1 hour"},
        {"Names": ["/marconi-agent-db"], "State": "running", "Status": "Up 1 hour"},
        {"Names": ["/extra-app"], "State": "running", "Status": "Up 1 hour"},
        {"Names": ["/untracked-sidecar"], "State": "exited", "Status": "Exited"},
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
    """With docker_name_filter empty, every container is in scope."""
    _use_settings(monkeypatch, docker_monitor=True, docker_name_filter="")
    monkeypatch.setattr(monitor, "list_watched_containers", list)
    monitor._container_state.clear()
    containers = [
        {"Names": ["/vllm"], "State": "running", "Status": "Up"},
        {"Names": ["/cadvisor"], "State": "running", "Status": "Up"},
    ]
    monkeypatch.setattr(monitor.docker, "list_containers", AsyncMock(return_value=containers))
    asyncio.run(monitor._poll_containers(MagicMock()))
    assert monitor._container_state == {"vllm": "running", "cadvisor": "running"}


def test_poll_containers_prunes_out_of_scope_state(monkeypatch):
    _use_settings(
        monkeypatch, docker_monitor=True, docker_name_filter="marconi-", discord_alert_channel_id=2
    )
    monkeypatch.setattr(monitor, "list_watched_containers", list)
    monitor._container_state.clear()
    monitor._container_state.update({"marconi-agent-api": "running", "old": "running"})

    containers = [{"Names": ["/marconi-agent-api"], "State": "running", "Status": "Up 1 hour"}]
    monkeypatch.setattr(monitor.docker, "list_containers", AsyncMock(return_value=containers))
    monkeypatch.setattr(monitor.discord_alert, "send_alert", AsyncMock())

    asyncio.run(monitor._poll_containers(MagicMock()))
    assert "old" not in monitor._container_state
    assert monitor._container_state == {"marconi-agent-api": "running"}


def test_poll_endpoints_alerts_on_down_then_recovery(monkeypatch):
    """Baseline poll is silent; unreachable -> critical, reachable again -> info."""
    _use_settings(
        monkeypatch,
        monitored_endpoints="loki=http://localhost:3100/ready",
        discord_alert_channel_id=1,
        discord_status_channel_id=2,
    )
    monkeypatch.setattr(monitor, "_endpoint_state", {})
    send_alert = AsyncMock()
    monkeypatch.setattr(monitor.discord_alert, "send_alert", send_alert)
    bot = MagicMock()

    monkeypatch.setattr(monitor, "probe", AsyncMock(return_value=True))
    asyncio.run(monitor._poll_endpoints(bot))
    send_alert.assert_not_awaited()

    monkeypatch.setattr(monitor, "probe", AsyncMock(return_value=False))
    asyncio.run(monitor._poll_endpoints(bot))
    send_alert.assert_awaited_once()
    args, kwargs = send_alert.await_args
    assert args[0] == 1
    assert kwargs["severity"] == "critical"
    assert "loki" in args[1]

    send_alert.reset_mock()
    monkeypatch.setattr(monitor, "probe", AsyncMock(return_value=True))
    asyncio.run(monitor._poll_endpoints(bot))
    send_alert.assert_awaited_once()
    args, kwargs = send_alert.await_args
    assert args[0] == 2
    assert kwargs["severity"] == "info"

    send_alert.reset_mock()
    asyncio.run(monitor._poll_endpoints(bot))
    send_alert.assert_not_awaited()


def test_poll_endpoints_prunes_removed_endpoints(monkeypatch):
    _use_settings(monkeypatch, monitored_endpoints="")
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
        assert asyncio.run(monitor.probe("http://x")) is expected

    monkeypatch.setattr(
        monitor.httpx, "AsyncClient",
        lambda *a, **kw: FakeClient(exc=monitor.httpx.ConnectError("refused")),
    )
    assert asyncio.run(monitor.probe("http://x")) is False


def test_poll_containers_logs_transitions_but_not_the_baseline(monkeypatch):
    """A transition must be recorded even with no alert channel configured; a baseline must not be."""
    from datetime import UTC, datetime, timedelta

    from agent.watchlist.repository import events_since

    _use_settings(
        monkeypatch,
        docker_monitor=True,
        discord_alert_channel_id=None,
        discord_status_channel_id=None,
    )
    monkeypatch.setattr(monitor, "list_watched_containers", list)
    monkeypatch.setattr(monitor.discord_alert, "send_alert", AsyncMock())
    monitor._container_state.clear()
    since = datetime.now(UTC) - timedelta(minutes=1)

    running = [{"Names": ["/marconi-agent-api"], "State": "running", "Status": "Up 1h"}]
    monkeypatch.setattr(monitor.docker, "list_containers", AsyncMock(return_value=running))
    asyncio.run(monitor._poll_containers(MagicMock()))
    assert events_since(since) == []

    stopped = [{"Names": ["/marconi-agent-api"], "State": "exited", "Status": "Exited"}]
    monkeypatch.setattr(monitor.docker, "list_containers", AsyncMock(return_value=stopped))
    asyncio.run(monitor._poll_containers(MagicMock()))

    logged = events_since(since)
    assert [(e["target"], e["kind"], e["state"]) for e in logged] == [
        ("marconi-agent-api", "container", "down")
    ]
    monitor.discord_alert.send_alert.assert_not_awaited()
