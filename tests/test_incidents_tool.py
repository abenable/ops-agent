"""Tests for incident action tools."""

from agent.storage.repository import store_incident
from agent.tools.incidents import acknowledge_incident, list_incidents, resolve_incident


def test_incident_lifecycle(tmp_database):
    incident_id = store_incident("web", "outage")

    ack = acknowledge_incident(incident_id)
    assert ack is not None
    assert ack["status"] == "acknowledged"

    resolved = resolve_incident(incident_id)
    assert resolved is not None
    assert resolved["status"] == "resolved"

    resolved_list = list_incidents(status="resolved")
    assert any(i["id"] == incident_id for i in resolved_list)
