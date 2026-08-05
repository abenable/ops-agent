"""Tests for controlled agent tools."""

import asyncio
from unittest.mock import AsyncMock

from agent.tools import docker
from agent.tools.logs import get_recent_logs
from agent.tools.metrics import _escape_label_value, get_service_metrics
from agent.tools.services import get_service_status
from agent.tools.sources import loki, prometheus


def test_escape_label_value_escapes_quotes_and_backslashes():
    assert _escape_label_value('a"b\\c') == 'a\\"b\\\\c'


def test_service_status_stub(monkeypatch):
    # Force the not-found stub path regardless of whether Docker is reachable.
    monkeypatch.setattr(docker, "find_container", AsyncMock(return_value=None))
    result = asyncio.run(get_service_status("web"))
    assert result["service"] == "web"
    assert result["status"] == "not found"


def test_metrics_stub(monkeypatch):
    # Force the fallback path regardless of whether Prometheus is reachable.
    monkeypatch.setattr(
        prometheus, "query_prometheus", AsyncMock(side_effect=RuntimeError("unreachable"))
    )
    result = asyncio.run(get_service_metrics("web"))
    assert result["service"] == "web"


def test_logs_stub(monkeypatch):
    # Force the fallback path regardless of whether Loki is reachable.
    monkeypatch.setattr(loki, "query_loki_range", AsyncMock(side_effect=RuntimeError("unreachable")))
    result = asyncio.run(get_recent_logs("web", lines=5))
    assert "web" in result
    assert "5 lines" in result
