"""Tests for the reporting workflow and create→report loop."""

from agent.storage.repository import store_incident
from agent.workflows.reporting import run_report_workflow


def test_report_workflow_not_found():
    message = run_report_workflow("missing-id")
    assert "no incident found" in message.lower()


def test_report_workflow_existing_incident(tmp_database):
    summary = "the service is on fire"
    incident_id = store_incident("web", summary)

    report = run_report_workflow(incident_id)

    assert incident_id in report
    assert summary in report
    assert "web" in report


def test_create_to_report_loop(tmp_database):
    incident_id = store_incident("api", "latency spike detected")

    report = run_report_workflow(incident_id)

    assert incident_id in report
    assert "latency spike detected" in report
    assert "api" in report
