"""Smoke tests for API routes."""

from fastapi.testclient import TestClient

from agent.api.server import app


client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
