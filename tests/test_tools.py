"""Tests for controlled agent tools."""

import asyncio
from unittest.mock import AsyncMock

from agent.helpers import docker
from agent.helpers.logs import get_recent_logs
from agent.helpers.metrics import _escape_label_value, get_service_metrics
from agent.helpers.services import get_service_status
from agent.helpers.sources import loki, prometheus


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


# --- label resolution: compose service key vs. Docker container name -------
#
# Loki/Prometheus label containers by the short docker-compose service key
# ('n8n'), while callers (web dashboard, Discord button targets) often pass
# the full container name ('marconi-agent-n8n'). Regression coverage for that
# mismatch and for metrics.py hardcoding a 'service' label + a metric name
# that doesn't exist for every job.


def test_resolve_label_name_uses_compose_service_label(monkeypatch):
    container = {
        "Id": "abc123",
        "Names": ["/marconi-agent-n8n"],
        "Labels": {"com.docker.compose.service": "n8n"},
    }
    monkeypatch.setattr(docker, "find_container", AsyncMock(return_value=container))
    assert asyncio.run(docker.resolve_label_name("marconi-agent-n8n")) == "n8n"


def test_resolve_label_name_falls_back_to_container_name_without_label(monkeypatch):
    container = {"Id": "abc123", "Names": ["/standalone"], "Labels": {}}
    monkeypatch.setattr(docker, "find_container", AsyncMock(return_value=container))
    assert asyncio.run(docker.resolve_label_name("standalone")) == "standalone"


def test_resolve_label_name_falls_back_to_input_when_no_container(monkeypatch):
    monkeypatch.setattr(docker, "find_container", AsyncMock(return_value=None))
    assert asyncio.run(docker.resolve_label_name("typo-name")) == "typo-name"


def test_get_recent_logs_queries_loki_with_compose_label_not_container_name(monkeypatch):
    """The full container name must never leak into the Loki selector — Loki's
    stream label is the short compose key, so a selector built from the full
    name (containing 'marconi') matches nothing."""
    container = {
        "Id": "abc123",
        "Names": ["/marconi-agent-n8n"],
        "Labels": {"com.docker.compose.service": "n8n"},
    }
    monkeypatch.setattr(docker, "find_container", AsyncMock(return_value=container))
    captured = {}

    async def fake_query_loki_range(query, minutes, limit):
        captured["query"] = query
        return {"data": {"result": [{"values": [[1, "log line"]]}]}}

    monkeypatch.setattr(loki, "query_loki_range", fake_query_loki_range)
    asyncio.run(get_recent_logs("marconi-agent-n8n", lines=5))
    assert "marconi" not in captured["query"]
    assert "n8n" in captured["query"]


def test_get_service_metrics_queries_by_job_label_not_service(monkeypatch):
    """No series in this stack carries a 'service' label (only 'job'), and no
    metric name is safe to hardcode across jobs — n8n's prom-client metrics
    are prefixed 'n8n_process_...', not 'process_...'. The query must be a
    bare job selector with no assumed metric name."""
    container = {
        "Id": "abc123",
        "Names": ["/marconi-agent-n8n"],
        "Labels": {"com.docker.compose.service": "n8n"},
    }
    monkeypatch.setattr(docker, "find_container", AsyncMock(return_value=container))
    captured = {}

    async def fake_query_prometheus(query):
        captured["query"] = query
        return {
            "data": {
                "result": [
                    {
                        "metric": {"__name__": "n8n_process_cpu_user_seconds_total", "job": "n8n"},
                        "value": [1, "1.2"],
                    }
                ]
            }
        }

    monkeypatch.setattr(prometheus, "query_prometheus", fake_query_prometheus)
    result = asyncio.run(get_service_metrics("marconi-agent-n8n"))
    assert captured["query"] == '{job="n8n"}'
    assert "service" not in captured["query"]
    assert "process_cpu_seconds_total" not in captured["query"]
    assert result["data"]["result"][0]["metric"]["__name__"] == "n8n_process_cpu_user_seconds_total"


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


def test_loki_get_label_values_rejects_path_injection():
    bad = ["foo/../bar", "a?b", "x#y", "../etc", "a/b", "a\\b", " with space", "1abc", ""]
    for label in bad:
        assert asyncio.run(loki.get_label_values(label)) == [], f"expected reject for {label!r}"


def test_loki_get_label_values_accepts_valid_label(monkeypatch):
    """Loki's label schema is a separate namespace from Prometheus's — this hits
    Loki's own /label/{name}/values endpoint, not Prometheus's."""
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": ["n8n"]}

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

    monkeypatch.setattr(loki.httpx, "AsyncClient", FakeClient)
    out = asyncio.run(loki.get_label_values("service"))
    assert out == ["n8n"]
    assert captured["url"].endswith("/loki/api/v1/label/service/values")
