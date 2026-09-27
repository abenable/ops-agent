"""Tests for the HTTP API."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from agent import api
from agent.watchlist.repository import add_watched_container, record_event

CONTAINERS = [
    {"Names": ["/marconi-agent-bot"], "State": "running", "Status": "Up 2 hours", "Image": "agent-bot"},
    {"Names": ["/loki"], "State": "exited", "Status": "Exited (1) 5m ago", "Image": "loki"},
]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api.docker, "list_containers", AsyncMock(return_value=CONTAINERS))
    monkeypatch.setattr(api, "get_monitored_endpoints", lambda: {"prom": "http://p/-/healthy"})
    monkeypatch.setattr(api, "probe", AsyncMock(return_value=True))
    monkeypatch.setattr(api.settings, "api_key", "")
    monkeypatch.setattr(api.settings, "docker_name_filter", "")
    return TestClient(api.app)


def test_health_needs_no_key_and_states_read_only(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["read_only"] is True


def test_status_separates_up_from_down(client):
    body = client.get("/status").json()
    assert body["containers_down"] == ["loki"]
    assert body["endpoints_down"] == []
    assert {c["name"] for c in body["containers"]} == {"marconi-agent-bot", "loki"}


def test_services_lists_names_and_endpoints(client):
    body = client.get("/services").json()
    assert set(body["containers"]) == {"marconi-agent-bot", "loki"}
    assert body["endpoints"] == {"prom": "http://p/-/healthy"}


def test_investigate_passes_the_question_through(client, monkeypatch):
    seen = {}

    async def _fake(question, thread_id=None):
        seen["question"], seen["thread_id"] = question, thread_id
        return "loki is down"

    monkeypatch.setattr(api, "investigate", _fake)
    body = client.post("/investigate", json={"question": "what is down?", "thread_id": "t1"}).json()
    assert body["answer"] == "loki is down"
    assert seen == {"question": "what is down?", "thread_id": "t1"}


def test_report_passes_the_service_through(client, monkeypatch):
    monkeypatch.setattr(api, "report", AsyncMock(return_value="**Summary** fine"))
    assert client.post("/report", json={"service": "loki"}).json()["answer"] == "**Summary** fine"


def test_digest_rejects_an_unknown_kind(client, monkeypatch):
    monkeypatch.setattr(api.digest, "build_daily", AsyncMock(return_value="body"))
    assert client.get("/digest/daily").json()["body"] == "body"
    assert client.get("/digest/hourly").status_code == 422


def test_events_window_is_bounded(client):
    record_event("loki", "container", "down")
    assert client.get("/events?hours=24").json()["count"] >= 1
    assert client.get("/events?hours=0").status_code == 422
    assert client.get(f"/events?hours={api.MAX_EVENT_HOURS + 1}").status_code == 422


def test_watchlist_add_then_remove(client):
    assert client.post("/watchlist", json={"container": "marconi-agent-bot"}).status_code == 201
    assert "marconi-agent-bot" in client.get("/watchlist").json()["containers"]
    # separator-agnostic, the same rule the slash command uses
    assert client.delete("/watchlist/marconi_agent_bot").json()["removed"] is True
    assert client.get("/watchlist").json()["containers"] == []


def test_removing_an_unwatched_container_is_404(client):
    assert client.delete("/watchlist/nope").status_code == 404


def test_docker_failure_is_503_not_500(client, monkeypatch):
    monkeypatch.setattr(api.docker, "list_containers", AsyncMock(side_effect=OSError("no socket")))
    response = client.get("/containers")
    assert response.status_code == 503
    assert "docker unavailable" in response.json()["detail"]


def test_api_key_gates_every_route_except_health(monkeypatch, client):
    monkeypatch.setattr(api.settings, "api_key", "secret")
    add_watched_container("loki")

    assert client.get("/health").status_code == 200

    guarded = [
        ("get", "/services"), ("get", "/containers"), ("get", "/status"),
        ("get", "/events"), ("get", "/digest/daily"), ("get", "/watchlist"),
        ("post", "/investigate"), ("post", "/investigate/stream"), ("post", "/report"),
        ("post", "/watchlist"), ("delete", "/watchlist/loki"),
        ("get", "/threads"), ("get", "/threads/any"), ("get", "/tools"),
    ]
    for method, path in guarded:
        kwargs = {"json": {}} if method == "post" else {}
        assert getattr(client, method)(path, **kwargs).status_code == 401, path
        wrong = getattr(client, method)(path, headers={"X-API-Key": "nope"}, **kwargs)
        assert wrong.status_code == 401, path


def test_investigate_rejects_an_empty_question(client):
    assert client.post("/investigate", json={"question": ""}).status_code == 422
    assert client.post("/investigate", json={}).status_code == 422
