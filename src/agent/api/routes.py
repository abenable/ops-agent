"""FastAPI routes exposed by the agent."""

import json

from fastapi import APIRouter, Request, Response
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from agent.api import activity
from agent.tasks import available_tasks, load_task
from agent.storage.repository import (
    add_watched_container,
    get_incident,
    list_incidents,
    list_pending_approvals,
    list_watched_containers,
    remove_watched_container,
    update_incident_status,
)
from agent.tools import docker
from agent.tools.health import check_endpoint
from agent.tools.logs import get_recent_logs
from agent.tools.metrics import get_service_metrics
from agent.tools.services import get_service_status
from agent.workflows.incident import (
    run_ask_workflow_stream,
    run_incident_workflow,
    run_incident_workflow_stream,
)
from agent.workflows.remediation import (
    execute_approval,
    reject_approval,
    run_remediation_workflow,
)

router = APIRouter(prefix="/api")


@router.get("/containers")
async def containers():
    """All Docker containers (running + stopped), grouped client-side by state."""
    return await docker.list_containers(all_containers=True)


@router.get("/watch/containers")
async def watched_containers():
    """Names of the containers the operator has selected to watch."""
    return {"containers": list_watched_containers()}


@router.put("/watch/containers/{name}")
async def watch_container(name: str):
    """Add a container to the watch list; status updates will include it."""
    add_watched_container(name)
    return {"containers": list_watched_containers()}


@router.delete("/watch/containers/{name}")
async def unwatch_container(name: str):
    """Remove a container from the watch list."""
    remove_watched_container(name)
    return {"containers": list_watched_containers()}


@router.get("/services/{service}/status")
async def service_status(service: str):
    return await get_service_status(service)


@router.get("/services/{service}/logs")
async def service_logs(service: str, lines: int = 10):
    return {"service": service, "lines": lines, "logs": await get_recent_logs(service, lines)}


@router.get("/services/{service}/metrics")
async def service_metrics(service: str):
    return await get_service_metrics(service)


@router.post("/incidents/{service}")
async def create_incident(service: str):
    return await run_incident_workflow(service)


class QuestionBody(BaseModel):
    question: str
    history: list[dict] | None = None


@router.post("/ask/stream")
async def ask_stream(body: QuestionBody):
    """SSE stream of the free-form agentic investigation loop.

    ``history`` carries prior turns (``{"role": "user"|"assistant", "content": ...}``)
    so the agent remembers the ongoing conversation.
    """

    async def gen():
        async for event in run_ask_workflow_stream(body.question, body.history):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/incidents/{service}/stream")
async def incident_stream(service: str):
    """SSE stream of the incident workflow; persists the incident at ``done``."""

    async def gen():
        async for event in run_incident_workflow_stream(service):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/incidents")
async def incidents(status: str | None = None, limit: int = 50):
    return list_incidents(status=status, limit=limit)


@router.get("/incidents/{incident_id}")
async def incident(incident_id: str):
    return get_incident(incident_id)


@router.get("/health-check")
async def health_check(url: str):
    return await check_endpoint(url)


@router.get("/tasks")
async def tasks():
    """List the available tasks under ``agent/eval/tasks/`` with their metadata."""
    out = []
    for name in available_tasks():
        data = load_task(name) or {}
        out.append(
            {
                "name": name,
                "title": data.get("name", name),
                "service": data.get("service"),
                "symptom": (data.get("symptom") or "").strip(),
                "expected_actions": data.get("expected_agent_actions", []),
            }
        )
    return out


@router.post("/tasks/{name}/stream")
async def task_stream(name: str):
    """SSE stream of a task run. Loads ``agent/eval/tasks/<name>.yml``, runs the
    incident workflow for its service with the task symptom as a hint, and
    persists the incident at ``done`` — mirrors the Discord task button.
    """
    data = load_task(name)
    if data is None:
        return Response(
            content=json.dumps({"type": "error", "message": f"no task named '{name}'"}),
            media_type="application/json",
            status_code=404,
        )

    service = data["service"]
    symptom = (data.get("symptom") or "").strip() or None

    async def gen():
        async for event in run_incident_workflow_stream(service, hint=symptom):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/incidents/{incident_id}/remediate")
async def remediate_incident(incident_id: str):
    """Run the gated remediation agent against an incident's stored diagnosis.
    Returns the remediator's summary and any pending proposals it created; does
    not execute a restart (that needs an approval below).
    """
    incident = get_incident(incident_id)
    if incident is None:
        return Response(
            content=json.dumps({"error": "incident not found"}),
            media_type="application/json",
            status_code=404,
        )
    result = await run_remediation_workflow(incident_id, incident["service"], incident["summary"])
    return result


@router.get("/approvals")
async def approvals(incident_id: str | None = None, status: str | None = None):
    """List pending remediation approvals, optionally filtered by incident/status."""
    return list_pending_approvals(incident_id=incident_id, status=status)


@router.post("/approvals/{approval_id}/approve")
async def approve_approval(approval_id: str):
    return await execute_approval(approval_id)


@router.post("/approvals/{approval_id}/reject")
async def reject_approval_endpoint(approval_id: str):
    return reject_approval(approval_id)


@router.post("/incidents/{incident_id}/resolve")
async def resolve_incident(incident_id: str):
    """Mark a stored incident resolved."""
    incident = update_incident_status(incident_id, "resolved")
    if incident is None:
        return Response(
            content=json.dumps({"error": "incident not found"}),
            media_type="application/json",
            status_code=404,
        )
    return incident


@router.get("/activity/stream")
async def activity_stream():
    """SSE stream of live agent log activity (INFO+). Yields a snapshot of
    recent history, then live events as they are logged in the API process.
    """
    import asyncio

    snapshot, q = activity.subscribe()

    async def gen():
        try:
            for evt in snapshot:
                yield f"data: {json.dumps(evt)}\n\n"
            while True:
                evt = await q.get()
                yield f"data: {json.dumps(evt)}\n\n"
        finally:
            activity.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream")
