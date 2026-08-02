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

# Incident investigations return ranked root-cause hypotheses with evidence, not a
# single narrative — operators can verify a ranked list fast, and the evidence trail
# builds trust in the diagnostic layer before any remediation is allowed.
INCIDENT_SYSTEM_PROMPT = SYSTEM_PROMPT + (
    " Produce 2-3 ranked root-cause hypotheses, most likely first. For each: "
    "a one-line claim, then the evidence that supports it (cite the specific metric "
    "value, log line, or container state you observed). "
    "If the evidence is weak, say so explicitly rather than guessing a cause. "
    "Do not propose remediation; that is a separate, human-gated step."
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


async def run_agentic_investigation_stream(
    prompt: str,
    *,
    system_prompt: str = SYSTEM_PROMPT,
    tools: list = TOOLS,
):
    """Async generator yielding events from the bounded tool-calling loop.

    One source of truth for the Discord path (collects the final ``done`` event)
    and the SSE path (streams events to the web UI). Event types: ``tool_call``,
    ``tool_result``, ``done``.
    """
    by_name = {t.name: t for t in tools}
    llm = get_llm().bind_tools(tools)
    messages = [SystemMessage(system_prompt), HumanMessage(prompt)]

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
            yield {"type": "tool_call", "step": step, "name": name, "args": args}
            try:
                out = await by_name[name].ainvoke(args)
            except Exception as exc:
                out = f"tool error: {exc}"
            messages.append(ToolMessage(str(out)[:4000], tool_call_id=tool_id))
            yield {"type": "tool_result", "step": step, "name": name, "result": str(out)[:2000]}

    # If we exited because of the step cap with pending tool calls, ask for a final summary
    # using a tool-less LLM so it returns prose instead of issuing more tool calls.
    if ai and ai.tool_calls:
        ai = await get_llm().ainvoke(messages)

    content = (ai.content if ai else "") or "No summary produced."
    yield {"type": "done", "content": content}


async def run_agentic_investigation(
    prompt: str,
    *,
    system_prompt: str = SYSTEM_PROMPT,
    tools: list = TOOLS,
) -> str:
    """Bounded tool-calling loop. Returns the LLM's final answer or a fallback message.

    Thin collector over :func:`run_agentic_investigation_stream` so the Discord path
    and the SSE path share one loop implementation.
    """
    async for event in run_agentic_investigation_stream(
        prompt, system_prompt=system_prompt, tools=tools
    ):
        if event["type"] == "done":
            return event["content"]
    return "No summary produced."


async def run_incident_workflow(service: str) -> dict:
    """Collect signals for a service and return an incident id and summary."""
    prompt = f"Investigate service {service}."
    try:
        summary = await run_agentic_investigation(prompt, system_prompt=INCIDENT_SYSTEM_PROMPT)
    except Exception as exc:
        logger.warning("Agentic workflow failed for %s: %s", service, exc)
        summary = await _static_summary(service)

    if not summary or summary == "No summary produced.":
        summary = await _static_summary(service)

    incident_id = store_incident(service, summary)
    return {"incident_id": incident_id, "summary": summary}


async def run_incident_workflow_stream(service: str):
    """Stream the incident investigation, then persist and yield the incident id at ``done``.

    Falls back to ``_static_summary`` on exception, mirroring the non-stream path, and
    emits an ``error`` event instead of raising so the SSE connection stays usable.
    """
    prompt = f"Investigate service {service}."
    try:
        async for event in run_agentic_investigation_stream(
            prompt, system_prompt=INCIDENT_SYSTEM_PROMPT
        ):
            if event["type"] == "done":
                summary = event["content"]
                if not summary or summary == "No summary produced.":
                    summary = await _static_summary(service)
                incident_id = store_incident(service, summary)
                yield {"type": "done", "incident_id": incident_id, "summary": summary}
            else:
                yield event
    except Exception as exc:
        logger.warning("Agentic workflow stream failed for %s: %s", service, exc)
        summary = await _static_summary(service)
        incident_id = store_incident(service, summary)
        yield {"type": "error", "message": str(exc), "incident_id": incident_id, "summary": summary}


async def run_ask_workflow_stream(question: str):
    """Stream a free-form agentic answer; does not persist an incident."""
    try:
        async for event in run_agentic_investigation_stream(question):
            yield event
    except Exception as exc:
        logger.warning("Ask workflow stream failed: %s", exc)
        yield {"type": "error", "message": str(exc)}


async def run_ask_workflow(question: str) -> str:
    """Free-form agentic answer; does not persist an incident."""
    try:
        return await run_agentic_investigation(question)
    except Exception as exc:
        logger.warning("Ask workflow failed: %s", exc)
        return f"Ask workflow failed ({exc}); the LLM may be offline or unsupported."


async def llm_supports_tool_calls() -> bool:
    """Probe whether the configured LLM can emit tool_calls via bind_tools.

    Sends a task that genuinely requires a tool rather than a vague 'pick a tool'
    prompt — a capable model then calls list_services, but a non-tool model answers
    in prose. The old vague prompt under-reported capable local models.
    """
    try:
        llm = get_llm().bind_tools(TOOLS)
        response = await llm.ainvoke(
            [
                SystemMessage("Use the provided tools to answer the user's question."),
                HumanMessage(
                    "List the running infrastructure containers by calling the "
                    "list_services tool."
                ),
            ]
        )
        return bool(response.tool_calls)
    except Exception:
        return False
