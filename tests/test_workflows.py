"""Tests for incident and reporting workflows."""

import asyncio
from unittest.mock import patch

from agent.storage.repository import list_incidents
from agent.workflows.incident import run_incident_workflow


class FakeLLM:
    async def ainvoke(self, prompt: str):
        return type("Response", (), {"content": "fake incident summary"})()


def test_incident_workflow(tmp_database):
    with patch("agent.workflows.incident.get_llm", return_value=FakeLLM()):
        result = asyncio.run(run_incident_workflow("web"))

    assert isinstance(result, dict)
    assert "incident_id" in result
    assert result["summary"] == "fake incident summary"

    rows = list_incidents()
    assert any(
        row["service"] == "web" and row["summary"] == result["summary"]
        for row in rows
    )
