"""Tests for controlled agent tools."""

import asyncio

from agent.tools.logs import get_recent_logs
from agent.tools.metrics import get_service_metrics
from agent.tools.services import get_service_status


def test_service_status_stub():
    result = asyncio.run(get_service_status("web"))
    assert result["service"] == "web"


def test_metrics_stub():
    result = asyncio.run(get_service_metrics("web"))
    assert result["service"] == "web"


def test_logs_stub():
    result = asyncio.run(get_recent_logs("web", lines=5))
    assert "web" in result
    assert "5 lines" in result
