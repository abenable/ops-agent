"""Tests for the background Discord endpoint monitor."""

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
        Settings(monitored_endpoints="api=http://x,,=bad,no-equals"),
    )
    assert monitor._endpoints() == {"api": "http://x"}


def test_endpoints_empty_by_default(monkeypatch):
    monkeypatch.setattr(monitor, "settings", Settings())
    assert monitor._endpoints() == {}


def test_poll_once_escalates_on_healthy_to_down(monkeypatch):
    settings = Settings(
        monitored_endpoints="web=http://localhost:8000",
        discord_status_channel_id=1,
        discord_alert_channel_id=2,
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
