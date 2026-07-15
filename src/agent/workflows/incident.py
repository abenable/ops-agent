"""Incident investigation workflow."""

from agent.llm.client import get_llm
from agent.storage.repository import store_incident
from agent.tools.logs import get_recent_logs
from agent.tools.metrics import get_service_metrics
from agent.tools.services import get_service_status


async def run_incident_workflow(service: str) -> dict:
    """Collect signals for a service and return an incident id and summary."""
    status = await get_service_status(service)
    metrics = await get_service_metrics(service)
    logs = await get_recent_logs(service, lines=20)

    prompt = (
        f"Service {service} has an open incident.\n"
        f"Status: {status}\n"
        f"Metrics: {metrics}\n"
        f"Logs: {logs}\n"
        "Write a one-paragraph incident summary."
    )

    try:
        summary = (await get_llm().ainvoke(prompt)).content
    except Exception as exc:  # LLM may be offline during early testing
        summary = f"LLM unavailable ({exc}); raw context: {prompt}"

    incident_id = store_incident(service, summary)
    return {"incident_id": incident_id, "summary": summary}
