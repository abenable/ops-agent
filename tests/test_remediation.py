"""Tests for the remediation agent and its human-in-the-loop gate."""

import asyncio
from unittest.mock import AsyncMock, patch

import agent.workflows.remediation as remediation
from agent.storage import repository
from agent.storage.repository import (
    get_pending_approval,
    list_pending_approvals,
    set_approval_status,
    store_incident,
    store_pending_approval,
)
from agent.workflows.remediation import (
    _is_expired,
    _make_propose_restart,
    execute_approval,
    reject_approval,
    run_remediation_workflow,
)


class FakeMessage:
    def __init__(self, content: str = "", tool_calls: list | None = None):
        self.content = content
        self.tool_calls = tool_calls or []


class FakeLLM:
    def __init__(self, responses: list | None = None):
        self._responses = responses or [FakeMessage("remediation summary")]
        self._index = 0

    def bind_tools(self, _tools):
        return self

    async def ainvoke(self, _messages):
        resp = self._responses[self._index]
        self._index += 1
        return resp


_FAKE_CONTAINER = {"Id": "abc123def456", "Names": ["/marconi-agent-api"], "State": "running"}


def _patched_find_container(monkeypatch):
    monkeypatch.setattr(
        remediation.docker, "find_container", AsyncMock(return_value=_FAKE_CONTAINER)
    )


def test_store_and_get_pending_approval(tmp_database):
    incident_id = store_incident("web", "diagnosis")
    approval_id = store_pending_approval(
        incident_id=incident_id,
        container_name="marconi-agent-api",
        container_id="abc123",
        action="restart_container",
    )
    row = get_pending_approval(approval_id)
    assert row is not None
    assert row["status"] == "pending"
    assert row["action"] == "restart_container"
    assert row["container_name"] == "marconi-agent-api"
    assert row["incident_id"] == incident_id


def test_set_approval_status(tmp_database):
    incident_id = store_incident("web", "diagnosis")
    approval_id = store_pending_approval(
        incident_id=incident_id, container_name="api", action="restart_container"
    )
    updated = set_approval_status(approval_id, "rejected")
    assert updated["status"] == "rejected"
    assert get_pending_approval(approval_id)["status"] == "rejected"


def test_list_pending_approvals_filters(tmp_database):
    incident_id = store_incident("web", "diagnosis")
    a1 = store_pending_approval(incident_id=incident_id, container_name="a", action="restart_container")
    store_pending_approval(incident_id=incident_id, container_name="b", action="restart_container")
    set_approval_status(a1, "approved")
    pending = list_pending_approvals(incident_id=incident_id, status="pending")
    assert len(pending) == 1
    assert pending[0]["container_name"] == "b"


def test_propose_restart_stores_pending_and_does_not_restart(tmp_database, monkeypatch):
    _patched_find_container(monkeypatch)
    restart_mock = AsyncMock(return_value={"restarted": True})
    monkeypatch.setattr(remediation.docker, "restart_container", restart_mock)

    incident_id = store_incident("web", "diagnosis")
    propose_restart = _make_propose_restart(incident_id)

    out = asyncio.run(propose_restart.ainvoke({"container": "agent_api"}))

    assert "approval_id=" in out
    assert "marconi-agent-api" in out
    restart_mock.assert_not_awaited()
    approval_id = out.split("approval_id=")[1].strip()
    assert get_pending_approval(approval_id)["status"] == "pending"


def test_execute_approval_runs_restart_and_marks_approved(tmp_database, monkeypatch):
    _patched_find_container(monkeypatch)
    restart_mock = AsyncMock(return_value={"container_id": "abc123", "restarted": True})
    monkeypatch.setattr(remediation.docker, "restart_container", restart_mock)

    incident_id = store_incident("web", "diagnosis")
    propose_restart = _make_propose_restart(incident_id)
    out = asyncio.run(propose_restart.ainvoke({"container": "agent_api"}))
    approval_id = out.split("approval_id=")[1].strip()

    result = asyncio.run(execute_approval(approval_id))

    assert result["ok"] is True
    restart_mock.assert_awaited_once()
    assert get_pending_approval(approval_id)["status"] == "approved"


def test_execute_approval_refuses_already_resolved(tmp_database, monkeypatch):
    restart_mock = AsyncMock(return_value={"restarted": True})
    monkeypatch.setattr(remediation.docker, "restart_container", restart_mock)

    incident_id = store_incident("web", "diagnosis")
    approval_id = store_pending_approval(
        incident_id=incident_id, container_name="api", action="restart_container"
    )
    set_approval_status(approval_id, "rejected")

    result = asyncio.run(execute_approval(approval_id))

    assert result["ok"] is False
    assert "already rejected" in result["error"]
    restart_mock.assert_not_awaited()


def test_concurrent_execute_approval_runs_restart_only_once(tmp_database, monkeypatch):
    """Two concurrent approvals for the same row must not double-execute the
    restart. The safety property is: restart runs at most once and exactly one
    caller wins; the loser refuses without touching Docker."""
    _patched_find_container(monkeypatch)
    restart_mock = AsyncMock(return_value={"container_id": "abc123", "restarted": True})
    monkeypatch.setattr(remediation.docker, "restart_container", restart_mock)

    incident_id = store_incident("web", "diagnosis")
    propose_restart = _make_propose_restart(incident_id)
    out = asyncio.run(propose_restart.ainvoke({"container": "agent_api"}))
    approval_id = out.split("approval_id=")[1].strip()

    async def both():
        import asyncio as _a
        return await _a.gather(execute_approval(approval_id), execute_approval(approval_id))

    a, b = asyncio.run(both())

    winners = [r for r in (a, b) if r["ok"]]
    losers = [r for r in (a, b) if not r["ok"]]
    assert len(winners) == 1
    assert len(losers) == 1
    assert losers[0]["error"].startswith("already ")
    restart_mock.assert_awaited_once()
    assert get_pending_approval(approval_id)["status"] == "approved"


def test_claim_pending_approval_is_atomic(tmp_database):
    """claim_pending_approval transitions pending -> running exactly once; a
    second claim on the same row loses without side effects."""
    from agent.storage.repository import claim_pending_approval

    incident_id = store_incident("web", "diagnosis")
    approval_id = store_pending_approval(
        incident_id=incident_id, container_name="api", action="restart_container"
    )

    assert claim_pending_approval(approval_id) is True
    assert get_pending_approval(approval_id)["status"] == "running"
    # Second claim loses: the row is no longer pending.
    assert claim_pending_approval(approval_id) is False
    assert get_pending_approval(approval_id)["status"] == "running"

    # A claim on a never-pending id also loses.
    assert claim_pending_approval("no-such-id") is False


def test_execute_approval_refuses_missing(tmp_database):
    result = asyncio.run(execute_approval("no-such-id"))
    assert result == {"ok": False, "error": "approval not found"}


def test_execute_approval_expires_old_request_and_does_not_restart(tmp_database, monkeypatch):
    restart_mock = AsyncMock(return_value={"restarted": True})
    monkeypatch.setattr(remediation.docker, "restart_container", restart_mock)
    monkeypatch.setattr(remediation, "_is_expired", lambda approval: True)

    incident_id = store_incident("web", "diagnosis")
    approval_id = store_pending_approval(
        incident_id=incident_id, container_name="api", action="restart_container"
    )

    result = asyncio.run(execute_approval(approval_id))

    assert result["ok"] is False
    assert result["error"] == "approval expired"
    restart_mock.assert_not_awaited()
    assert get_pending_approval(approval_id)["status"] == "expired"


def test_execute_approval_marks_failed_on_restart_error(tmp_database, monkeypatch):
    monkeypatch.setattr(
        remediation.docker, "restart_container", AsyncMock(side_effect=RuntimeError("boom"))
    )

    incident_id = store_incident("web", "diagnosis")
    approval_id = store_pending_approval(
        incident_id=incident_id, container_name="api", container_id="cid", action="restart_container"
    )

    result = asyncio.run(execute_approval(approval_id))

    assert result["ok"] is False
    assert "restart failed" in result["error"]
    assert get_pending_approval(approval_id)["status"] == "failed"


def test_reject_approval_marks_rejected(tmp_database):
    incident_id = store_incident("web", "diagnosis")
    approval_id = store_pending_approval(
        incident_id=incident_id, container_name="api", action="restart_container"
    )
    result = reject_approval(approval_id)
    assert result["ok"] is True
    assert get_pending_approval(approval_id)["status"] == "rejected"


def test_reject_approval_refuses_missing(tmp_database):
    result = reject_approval("no-such-id")
    assert result == {"ok": False, "error": "approval not found"}


def test_is_expired_respects_ttl(monkeypatch, tmp_database):
    monkeypatch.setattr(remediation.settings, "remediation_approval_ttl_seconds", 300)
    fresh = {"created_at": remediation.datetime.now(remediation.timezone.utc).isoformat()}
    assert _is_expired(fresh) is False

    from datetime import datetime, timedelta, timezone

    old = {"created_at": (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()}
    assert _is_expired(old) is True

    monkeypatch.setattr(remediation.settings, "remediation_approval_ttl_seconds", 0)
    assert _is_expired(old) is False


def test_run_remediation_workflow_returns_pending_proposals(tmp_database, monkeypatch):
    _patched_find_container(monkeypatch)
    monkeypatch.setattr(remediation.docker, "restart_container", AsyncMock())

    incident_id = store_incident("web", "diagnosis text")
    responses = [
        FakeMessage(
            content="",
            tool_calls=[{"name": "propose_restart", "args": {"container": "agent_api"}, "id": "c1"}],
        ),
        FakeMessage(content="I propose a restart; awaiting approval."),
    ]

    with patch("agent.workflows.incident.get_llm", return_value=FakeLLM(responses)):
        result = asyncio.run(run_remediation_workflow(incident_id, "web", "diagnosis text"))

    assert result["incident_id"] == incident_id
    assert "awaiting approval" in result["summary"]
    assert len(result["proposals"]) == 1
    assert result["proposals"][0]["container_name"] == "marconi-agent-api"
    assert result["proposals"][0]["status"] == "pending"


def test_run_remediation_workflow_no_proposal(tmp_database, monkeypatch):
    incident_id = store_incident("web", "diagnosis text")
    with patch(
        "agent.workflows.incident.get_llm",
        return_value=FakeLLM([FakeMessage("No restart warranted; investigate further.")]),
    ):
        result = asyncio.run(run_remediation_workflow(incident_id, "web", "diagnosis text"))
    assert result["proposals"] == []


def test_kill_switch_blocks_remediation_workflow(tmp_database, monkeypatch):
    monkeypatch.setattr(remediation.settings, "remediation_enabled", False)
    llm = FakeLLM([FakeMessage("should not be called")])
    with patch("agent.workflows.incident.get_llm", return_value=llm) as get_llm_mock:
        result = asyncio.run(run_remediation_workflow("inc-1", "web", "diagnosis"))
    assert result["proposals"] == []
    assert "disabled" in result["summary"].lower()
    get_llm_mock.assert_not_called()


def test_kill_switch_blocks_execute_approval(tmp_database, monkeypatch):
    restart_mock = AsyncMock(return_value={"restarted": True})
    monkeypatch.setattr(remediation.docker, "restart_container", restart_mock)
    monkeypatch.setattr(remediation.settings, "remediation_enabled", False)

    approval_id = store_pending_approval(
        incident_id="inc-1", container_name="api", action="restart_container"
    )
    result = asyncio.run(execute_approval(approval_id))

    assert result["ok"] is False
    assert "disabled" in result["error"]
    restart_mock.assert_not_awaited()


def test_kill_switch_off_allows_execute(tmp_database, monkeypatch):
    restart_mock = AsyncMock(return_value={"container_id": "abc", "restarted": True})
    monkeypatch.setattr(remediation.docker, "restart_container", restart_mock)
    monkeypatch.setattr(remediation.settings, "remediation_enabled", True)

    approval_id = store_pending_approval(
        incident_id="inc-1", container_name="api", container_id="abc", action="restart_container"
    )
    result = asyncio.run(execute_approval(approval_id))
    assert result["ok"] is True
    restart_mock.assert_awaited_once()
