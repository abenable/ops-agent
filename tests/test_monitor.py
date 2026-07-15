"""Tests for the background Discord endpoint monitor."""

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
