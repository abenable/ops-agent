"""Remediation agent: proposes Docker restarts behind a human-in-the-loop gate.

This is the second agent in the multi-agent system. It reuses the investigator's
tool-calling loop (``run_agentic_investigation``) with its own system prompt and a
tool subset. Its only write tool, ``propose_restart``, does NOT execute a restart —
it records a pending approval in storage and returns the approval id to the LLM.
The actual restart only runs through ``execute_approval``, which a human triggers
via Discord buttons (``RemediationApprovalView``) or ``!approve`` / ``!reject``.
"""

import logging
from datetime import datetime, timezone

from langchain_core.tools import tool

from agent.config.settings import settings
from agent.storage import repository
from agent.tools import docker
from agent.tools.query_tools import docker_status, list_services
from agent.workflows.incident import run_agentic_investigation

logger = logging.getLogger(__name__)

REMEDIATION_PROMPT = (
    "You are Oracle-Remediate, the remediation agent for an infrastructure incident. "
    "You receive the investigator's diagnosis and decide whether a Docker container "
    "restart is the right action. "
    "Call list_services first to get real container names, and docker_status to confirm "
    "the suspect container's state. If a restart is appropriate, call propose_restart "
    "with the exact container name; it will NOT execute immediately — a human must "
    "approve it. Propose at most one restart per incident. "
    "If a restart is not appropriate, say why and propose nothing. "
    "End with one short paragraph stating the proposed action (if any) and that it is "
    "awaiting human approval."
)

READ_ONLY_TOOLS = [list_services, docker_status]


def _make_propose_restart(incident_id: str):
    """Build a propose_restart tool bound to this incident.

    The incident_id is closed over (not taken from the LLM) so the model cannot
    fake or misroute an approval to another incident.
    """

    @tool
    async def propose_restart(container: str) -> str:
        """Propose restarting a Docker container. Does NOT execute the restart —
        the action is recorded and a human must approve it before it runs.
        Use a container name returned by list_services. Returns the approval id
        to include in your summary."""
        target = await docker.find_container(container)
        if target is None:
            return f"(no container matching '{container}'; no action proposed)"
        name = docker.container_name(target)
        cid = target.get("Id") or name
        approval_id = repository.store_pending_approval(
            incident_id=incident_id,
            container_name=name,
            container_id=cid,
            action="restart_container",
        )
        logger.info("Proposed restart of %s for incident %s (approval %s)", name, incident_id, approval_id)
        return (
            f"Proposed restart of container '{name}' (id {cid[:12]}). "
            f"Awaiting human approval. approval_id={approval_id}"
        )

    return propose_restart


async def run_remediation_workflow(incident_id: str, service: str, diagnosis: str) -> dict:
    """Run the remediator against an existing incident's diagnosis.

    Returns the remediator's summary and the list of pending approvals it created.
    Does not execute any restart — that is the human's job via execute_approval.
    """
    if not settings.remediation_enabled:
        return {
            "incident_id": incident_id,
            "summary": "Remediation is disabled (kill switch). No action proposed.",
            "proposals": [],
        }
    propose_restart = _make_propose_restart(incident_id)
    tools = [*READ_ONLY_TOOLS, propose_restart]
    prompt = (
        f"Incident diagnosis for service '{service}' (incident {incident_id}):\n"
        f"{diagnosis}\n\n"
        "Decide whether a Docker container restart is the right remediation, then "
        "either propose it (propose_restart) or explain why not."
    )
    try:
        summary = await run_agentic_investigation(
            prompt, system_prompt=REMEDIATION_PROMPT, tools=tools
        )
    except Exception as exc:
        logger.warning("Remediation workflow failed for incident %s: %s", incident_id, exc)
        summary = f"Remediation workflow failed ({exc})."

    proposals = repository.list_pending_approvals(incident_id=incident_id, status="pending")
    return {"incident_id": incident_id, "summary": summary, "proposals": proposals}


async def execute_approval(approval_id: str) -> dict:
    """Execute a pending approval. Only path that calls docker.restart_container.

    Refuses to run if the kill switch is off, the approval is missing, already
    resolved, or older than the configured TTL (in which case it is marked expired).
    """
    if not settings.remediation_enabled:
        return {"ok": False, "error": "remediation disabled (kill switch)"}
    approval = repository.get_pending_approval(approval_id)
    if approval is None:
        return {"ok": False, "error": "approval not found"}
    if approval["status"] != "pending":
        return {"ok": False, "error": f"already {approval['status']}"}

    if _is_expired(approval):
        repository.set_approval_status(approval_id, "expired")
        return {"ok": False, "error": "approval expired"}

    container_id = approval.get("container_id") or approval["container_name"]
    try:
        result = await docker.restart_container(container_id)
    except Exception as exc:
        repository.set_approval_status(approval_id, "failed")
        return {"ok": False, "error": f"restart failed: {exc}"}

    repository.set_approval_status(approval_id, "approved")
    return {"ok": True, "result": result, "approval": approval}


def reject_approval(approval_id: str) -> dict:
    """Mark a pending approval rejected. Returns the updated approval or an error dict."""
    approval = repository.get_pending_approval(approval_id)
    if approval is None:
        return {"ok": False, "error": "approval not found"}
    if approval["status"] != "pending":
        return {"ok": False, "error": f"already {approval['status']}"}
    repository.set_approval_status(approval_id, "rejected")
    return {"ok": True, "approval": approval}


def _is_expired(approval: dict) -> bool:
    """True if the approval is older than the configured TTL."""
    ttl = settings.remediation_approval_ttl_seconds
    if ttl <= 0:
        return False
    try:
        created = datetime.fromisoformat(approval["created_at"])
    except (ValueError, KeyError):
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - created).total_seconds()
    return age > ttl


if __name__ == "__main__":
    # ponytail: self-check — execute_approval refuses a non-existent id without
    # touching Docker. Fails loudly if the gate's guard logic regresses.
    import asyncio

    out = asyncio.run(execute_approval("does-not-exist"))
    assert out == {"ok": False, "error": "approval not found"}, out
    print("remediation gate self-check ok")
