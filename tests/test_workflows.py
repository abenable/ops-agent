"""Tests for incident and reporting workflows."""

import pytest


@pytest.mark.skip(reason="requires a running LLM or mocked client")
def test_incident_workflow():
    from agent.workflows.incident import run_incident_workflow

    result = run_incident_workflow("web")
    assert isinstance(result, str)
