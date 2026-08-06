"""Smoke tests for API routes."""

from fastapi.testclient import TestClient

from agent.api.server import app


client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_watch_container_lifecycle(tmp_database):
    response = client.get("/api/watch/containers")
    assert response.status_code == 200
    assert response.json() == {"containers": []}

    response = client.put("/api/watch/containers/marconi-agent-api")
    assert response.status_code == 200
    assert "marconi-agent-api" in response.json()["containers"]

    response = client.delete("/api/watch/containers/marconi-agent-api")
    assert response.status_code == 200
    assert "marconi-agent-api" not in response.json()["containers"]

    response = client.get("/api/watch/containers")
    assert response.json() == {"containers": []}


def test_tasks_list_has_real_tasks():
    response = client.get("/api/tasks")
    assert response.status_code == 200
    names = {s["name"] for s in response.json()}
    assert "api_down" in names
    # each entry carries the metadata the web cards render
    sample = next(s for s in response.json() if s["name"] == "api_down")
    assert sample["service"] == "api"
    assert sample["expected_actions"]


def test_task_stream_unknown_returns_404():
    response = client.post("/api/tasks/does-not-exist/stream")
    assert response.status_code == 404


def test_resolve_incident_unknown_returns_404():
    response = client.post("/api/incidents/no-such-id/resolve")
    assert response.status_code == 404


def test_remediate_incident_unknown_returns_404():
    response = client.post("/api/incidents/no-such-id/remediate")
    assert response.status_code == 404


def test_approve_unknown_returns_approval_not_found():
    response = client.post("/api/approvals/no-such-id/approve")
    assert response.json()["ok"] is False
    assert "not found" in response.json()["error"]
