"""FastAPI routes exposed by the agent."""

from fastapi import APIRouter

from agent.tools.logs import get_recent_logs
from agent.tools.metrics import get_service_metrics
from agent.tools.services import get_service_status
from agent.workflows.incident import run_incident_workflow

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/services/{service}/status")
async def service_status(service: str):
    return await get_service_status(service)


@router.get("/services/{service}/logs")
async def service_logs(service: str, lines: int = 10):
    return await get_recent_logs(service, lines)


@router.get("/services/{service}/metrics")
async def service_metrics(service: str):
    return await get_service_metrics(service)


@router.post("/incidents/{service}")
async def create_incident(service: str):
    return {"summary": run_incident_workflow(service)}
