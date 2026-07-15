"""Incident investigation workflow."""

import asyncio

from agent.llm.client import get_llm
from agent.storage.repository import store_incident
from agent.tools.logs import get_recent_logs
from agent.tools.metrics import get_service_metrics
from agent.tools.services import get_service_status


def run_incident_workflow(service: str) -> str:
    """Collect signals for a service and return a short incident summary."""
    status = asyncio.run(get_service_status(service))
    metrics = asyncio.run(get_service_metrics(service))
    logs = asyncio.run(get_recent_logs(service, lines=20))

    prompt = (
        f"Service {service} has an open incident.\n"
        f"Status: {status}\n"
        f"Metrics: {metrics}\n"
        f"Logs: {logs}\n"
        "Write a one-paragraph incident summary."
    )

    try:
        summary = get_llm().invoke(prompt).content
    except Exception as exc:  # LLM may be offline during early testing
        summary = f"LLM unavailable ({exc}); raw context: {prompt}"

    store_incident(service, summary)
    return summary
