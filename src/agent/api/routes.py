"""FastAPI routes exposed by the agent."""

import json

from fastapi import APIRouter, Request, Response
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from agent.api import activity
from agent.tasks import available_tasks, load_task
from agent.memory.repository import (
    add_watched_container,
    list_watched_containers,
    remove_watched_container,
)
from agent.helpers import docker
from agent.helpers.logs import get_recent_logs
from agent.helpers.metrics import get_service_metrics
from agent.helpers.services import get_service_status
from agent.workflows.incident import run_agentic_investigation_stream, run_ask_workflow_stream

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
    """SSE stream of a task run. Loads ``agent/eval/tasks/<name>.yml`` and runs
    the agentic investigation loop for its service with the task symptom as a
    hint — mirrors the Discord task button.
    """
    data = load_task(name)
    if data is None:
        return Response(
            content=json.dumps({"type": "error", "message": f"no task named '{name}'"}),
            media_type="application/json",
            status_code=404,
        )

    prompt = f"Investigate service {data['service']}."
    symptom = (data.get("symptom") or "").strip()
    if symptom:
        prompt += f" Reported symptom: {symptom}"

    async def gen():
        async for event in run_agentic_investigation_stream(prompt):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


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
