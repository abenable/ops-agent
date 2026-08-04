"""FastAPI routes exposed by the agent."""

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.storage.repository import (
    add_watched_container,
    get_incident,
    list_incidents,
    list_watched_containers,
    remove_watched_container,
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

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok"}


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


@router.post("/ask/stream")
async def ask_stream(body: QuestionBody):
    """SSE stream of the free-form agentic investigation loop."""

    async def gen():
        async for event in run_ask_workflow_stream(body.question):
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
