"""Tests for the clickable scenario runner panel."""

import asyncio
from unittest.mock import AsyncMock, patch

import agent.bot.scenarios as scenarios


def test_available_scenarios_lists_repo_files():
    names = scenarios._available_scenarios()
    assert "api_down" in names
    assert "scrape_target_down" in names
    assert all(n and "/" not in n for n in names)


def test_run_and_post_runs_workflow_with_symptom_hint(monkeypatch):
    captured = {}

    async def fake_run(service, hint=None):
        captured["service"] = service
        captured["hint"] = hint
        return {"incident_id": "abc123", "summary": "diagnosis of api"}

    monkeypatch.setattr(scenarios, "run_incident_workflow", fake_run)

    sent: list[str] = []

    async def send(msg):
        sent.append(msg)

    asyncio.run(scenarios._run_and_post("api_down", send))

    assert captured["service"] == "api"
    assert captured["hint"] and "api" in captured["hint"].lower()
    assert any("Simulating" in m for m in sent)
    assert any("diagnosis of api" in m for m in sent)


def test_run_and_post_handles_missing_scenario(monkeypatch):
    monkeypatch.setattr(scenarios, "run_incident_workflow", AsyncMock())
    sent: list[str] = []

    async def send(msg):
        sent.append(msg)

    asyncio.run(scenarios._run_and_post("does_not_exist", send))
    assert sent and "No scenario" in sent[0]
