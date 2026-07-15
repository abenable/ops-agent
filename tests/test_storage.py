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


def test_update_thread_id(tmp_database):
    from agent.storage.repository import update_incident_thread_id

    incident_id = store_incident("test-svc", "summary text")
    updated = update_incident_thread_id(incident_id, 123456789)
    assert updated is not None
    assert updated["thread_id"] == 123456789
    assert get_incident(incident_id)["thread_id"] == 123456789
