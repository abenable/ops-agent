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


def test_watch_list_roundtrip(tmp_database):
    from agent.storage.repository import (
        add_watched_container,
        find_watched_container,
        is_watched,
        list_watched_containers,
        remove_watched_container,
    )

    assert list_watched_containers() == []
    assert add_watched_container("marconi-agent-api") is True
    assert add_watched_container("marconi-agent-api") is False
    assert is_watched("marconi-agent-api") is True
    assert list_watched_containers() == ["marconi-agent-api"]

    # Separator-agnostic resolution on remove.
    assert remove_watched_container("agent_api") is True
    assert list_watched_containers() == []
    assert remove_watched_container("agent_api") is False


def test_find_watched_container_matches_variants(tmp_database):
    from agent.storage.repository import add_watched_container, find_watched_container

    add_watched_container("marconi-agent-api")
    assert find_watched_container("agent_api") == "marconi-agent-api"
    assert find_watched_container("agent-api") == "marconi-agent-api"
    assert find_watched_container("nonexistent") is None
