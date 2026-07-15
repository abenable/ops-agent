"""Tests for the incident repository."""

from agent.storage.repository import (
    get_incident,
    list_incidents,
    store_incident,
    update_incident_status,
)


def test_store_and_get_incident(tmp_database):
    incident_id = store_incident("test-svc", "summary text")
    row = get_incident(incident_id)
    assert row is not None
    assert row["service"] == "test-svc"
    assert row["summary"] == "summary text"
    assert row["status"] == "open"


def test_get_missing_incident(tmp_database):
    assert get_incident("does-not-exist") is None


def test_update_status_and_list(tmp_database):
    incident_id = store_incident("test-svc", "summary text")
    updated = update_incident_status(incident_id, "acknowledged")
    assert updated is not None
    assert updated["status"] == "acknowledged"

    open_incidents = list_incidents(status="open")
    assert not any(i["id"] == incident_id for i in open_incidents)

    ack_incidents = list_incidents(status="acknowledged")
    assert any(i["id"] == incident_id for i in ack_incidents)
