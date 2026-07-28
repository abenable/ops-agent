"""Incident investigation workflow."""

import logging

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from agent.config.settings import settings
from agent.llm.client import get_llm
from agent.storage.repository import store_incident
from agent.tools.logs import get_recent_logs
from agent.tools.metrics import get_service_metrics
from agent.tools.query_tools import (
    docker_logs,
    docker_status,
    get_label_values,
    list_metric_names,
    list_services,
    query_loki,
    query_loki_range,
    query_prometheus,
    query_prometheus_range,
)
from agent.tools.services import get_service_status

logger = logging.getLogger(__name__)

TOOLS = [
    list_services,
    docker_status,
    docker_logs,
    query_prometheus,
    list_metric_names,
    get_label_values,
    query_prometheus_range,
    query_loki,
    query_loki_range,
]

SYSTEM_PROMPT = (
    "You are Oracle, an infrastructure-operations investigator. "
    "Start by calling list_services to learn the real container and endpoint names, "
    "then discover metric names and label values. "
    "Use the actual names you discover, not the user's spelling, for your queries. "
    "Use docker_status and docker_logs to inspect containers Prometheus/Loki do not cover. "
    "Write cheap PromQL/LogQL queries and prefer short time windows. "
    "Summarize findings in one paragraph."
)


async def _static_summary(service: str) -> str:
    """Fallback summary when the agentic loop is unavailable or yields nothing."""
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
        return (await get_llm().ainvoke(prompt)).content
    except Exception as exc:  # LLM may be offline during early testing
        return f"LLM unavailable ({exc}); raw context: {prompt}"


async def run_agentic_investigation(prompt: str) -> str:
    """Bounded tool-calling loop. Returns the LLM's final answer or a fallback message."""
    by_name = {t.name: t for t in TOOLS}
    llm = get_llm().bind_tools(TOOLS)
    messages = [SystemMessage(SYSTEM_PROMPT), HumanMessage(prompt)]

    ai = None
    for step in range(settings.max_tool_steps):
        ai = await llm.ainvoke(messages)
        messages.append(ai)
        if not ai.tool_calls:
            break

        for call in ai.tool_calls:
            name = call.get("name")
            args = call.get("args") or {}
            tool_id = call.get("id", "call")
            logger.info("Tool call: %s(%s)", name, args)
            try:
                out = await by_name[name].ainvoke(args)
            except Exception as exc:
                out = f"tool error: {exc}"
            messages.append(ToolMessage(str(out)[:4000], tool_call_id=tool_id))

    # If we exited because of the step cap with pending tool calls, ask for a final summary
    # using a tool-less LLM so it returns prose instead of issuing more tool calls.
    if ai and ai.tool_calls:
        ai = await get_llm().ainvoke(messages)

    return (ai.content if ai else "") or "No summary produced."


async def run_incident_workflow(service: str) -> dict:
    """Collect signals for a service and return an incident id and summary."""
    prompt = f"Investigate service {service}."
    try:
        summary = await run_agentic_investigation(prompt)
    except Exception as exc:
        logger.warning("Agentic workflow failed for %s: %s", service, exc)
        summary = await _static_summary(service)

    if not summary or summary == "No summary produced.":
        summary = await _static_summary(service)

    incident_id = store_incident(service, summary)
    return {"incident_id": incident_id, "summary": summary}


async def run_ask_workflow(question: str) -> str:
    """Free-form agentic answer; does not persist an incident."""
    try:
        return await run_agentic_investigation(question)
    except Exception as exc:
        logger.warning("Ask workflow failed: %s", exc)
        return f"Ask workflow failed ({exc}); the LLM may be offline or unsupported."


async def llm_supports_tool_calls() -> bool:
    """Probe the configured LLM to see if it can emit tool_calls via bind_tools."""
    try:
        llm = get_llm().bind_tools(TOOLS)
        response = await llm.ainvoke([HumanMessage("Pick a tool to call.")])
        return bool(response.tool_calls)
    except Exception:
        return False
