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
    # Force the Loki path to raise; the Docker fallback will also fail (no socket in CI).
    monkeypatch.setattr(loki, "query_loki_range", AsyncMock(side_effect=RuntimeError("unreachable")))
    result = asyncio.run(get_recent_logs("web", lines=5))
    assert result == "No logs."


def test_get_label_values_rejects_path_injection():
    """The label arg is LLM-controlled and interpolated into the URL path; invalid
    labels must be refused rather than sent to Prometheus, preventing path/query
    manipulation (e.g. 'foo/../bar', 'a?b', 'x#y')."""
    bad = ["foo/../bar", "a?b", "x#y", "../etc", "a/b", "a\\b", " with space", "1abc", ""]
    for label in bad:
        assert asyncio.run(prometheus.get_label_values(label)) == [], f"expected reject for {label!r}"


def test_get_label_values_accepts_valid_label(monkeypatch):
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": ["web", "api"]}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None):
            captured["url"] = url
            return FakeResp()

    monkeypatch.setattr(prometheus.httpx, "AsyncClient", FakeClient)
    out = asyncio.run(prometheus.get_label_values("job"))
    assert out == ["web", "api"]
    assert captured["url"].endswith("/api/v1/label/job/values")
