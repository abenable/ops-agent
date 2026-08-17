"""Tests for the minimal Docker/Prometheus/Loki clients inside agent.tools."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from agent.tools import loki, prometheus
from agent.tools.docker import _demux_docker_stream, container_name


def _fake_http_client(json_payload=None):
    """A mocked httpx.AsyncClient context manager + its inner client."""

    class FakeResponse:
        content = b""

        def raise_for_status(self):
            pass

        def json(self):
            return json_payload if json_payload is not None else {}

    fake_client = MagicMock()
    fake_client.get = AsyncMock(return_value=FakeResponse())
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=fake_client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return fake_client, cm


def test_prometheus_token_sent_only_when_set(monkeypatch):
    monkeypatch.setattr(prometheus.settings, "prometheus_token", "")
    _, cm = _fake_http_client()
    with patch.object(prometheus.httpx, "AsyncClient", return_value=cm) as Client:
        asyncio.run(prometheus.query("up"))
    assert Client.call_args.kwargs["timeout"] == 10.0
    assert Client.call_args.kwargs["headers"] == {}

    monkeypatch.setattr(prometheus.settings, "prometheus_token", "secret")
    with patch.object(prometheus.httpx, "AsyncClient", return_value=cm) as Client:
        asyncio.run(prometheus.query("up"))
    assert Client.call_args.kwargs["headers"] == {"Authorization": "Bearer secret"}


def test_prometheus_label_values_rejects_invalid_label():
    assert asyncio.run(prometheus.label_values("bad label!")) == []


def test_loki_token_sent_only_when_set(monkeypatch):
    monkeypatch.setattr(loki.settings, "loki_token", "")
    _, cm = _fake_http_client()
    with patch.object(loki.httpx, "AsyncClient", return_value=cm) as Client:
        asyncio.run(loki.query('{app="x"}'))
    assert Client.call_args.kwargs["headers"] == {}

    monkeypatch.setattr(loki.settings, "loki_token", "secret")
    with patch.object(loki.httpx, "AsyncClient", return_value=cm) as Client:
        asyncio.run(loki.query('{app="x"}'))
    assert Client.call_args.kwargs["headers"] == {"Authorization": "Bearer secret"}


def test_loki_query_uses_range_endpoint_not_instant():
    """Regression: Loki's instant /query endpoint rejects plain log-stream
    selectors, so query() must delegate to /query_range, not /query."""
    fake_client, cm = _fake_http_client(json_payload={"status": "success"})
    with patch.object(loki.httpx, "AsyncClient", return_value=cm):
        asyncio.run(loki.query('{container="x"}'))

    url = fake_client.get.call_args.args[0]
    assert url.endswith("/loki/api/v1/query_range")
    assert "start" in fake_client.get.call_args.kwargs["params"]


def test_loki_label_values_rejects_invalid_label():
    assert asyncio.run(loki.label_values("bad label!")) == []


def test_container_name_strips_leading_slash():
    assert container_name({"Names": ["/marconi-agent-api"]}) == "marconi-agent-api"
    assert container_name({"Names": [], "Id": "abcdef1234567890"}) == "abcdef123456"


def test_demux_docker_stream_strips_framing():
    payload = b"hello\nworld\n"
    frame = b"\x01\x00\x00\x00" + len(payload).to_bytes(4, "big") + payload
    assert _demux_docker_stream(frame) == "hello\nworld\n"
