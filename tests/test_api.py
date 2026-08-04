"""Smoke tests for API routes."""

from fastapi.testclient import TestClient

from agent.api.server import app


client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_watch_container_lifecycle(tmp_database):
    response = client.get("/watch/containers")
    assert response.status_code == 200
    assert response.json() == {"containers": []}

    response = client.put("/watch/containers/marconi-agent-api")
    assert response.status_code == 200
    assert "marconi-agent-api" in response.json()["containers"]

    response = client.delete("/watch/containers/marconi-agent-api")
    assert response.status_code == 200
    assert "marconi-agent-api" not in response.json()["containers"]

    response = client.get("/watch/containers")
    assert response.json() == {"containers": []}
