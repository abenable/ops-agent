"""Tests for the HTTP health tool."""

import asyncio

from agent.tools.health import check_endpoint


def test_health_unreachable():
    result = asyncio.run(check_endpoint("http://localhost:59999/unreachable", timeout=1.0))
    assert result["reachable"] is False
    assert result["status_code"] is None
    assert "error" in result
