"""Incident investigation workflow."""

import logging
import re
import time

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

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

# DeepSeek sometimes emits tool calls inline in ``content`` using its native
# ``<｜｜DSML｜｜>`` XML instead of the OpenAI ``tool_calls`` field the loop reads.
# When that happens the calls are never executed and the raw XML leaks into the
# summary (and the Discord incident thread). We parse those inline calls back
# into the structured shape the loop already handles, and strip any residual
# markup from final prose. ``｜`` is U+FF5C (fullwidth vertical line).
_PIPE = "\uFF5C"
_TOK = _PIPE + _PIPE + "DSML" + _PIPE + _PIPE  # ｜｜DSML｜｜
_DSML_BLOCK_RE = re.compile(r"<" + re.escape(_TOK) + r"tool_calls>.*?</" + re.escape(_TOK) + r"tool_calls>", re.DOTALL)
_DSML_TAG_RE = re.compile(r"</?" + re.escape(_TOK) + r"[^>]*>")
_INVOKE_RE = re.compile(r"<" + re.escape(_TOK) + r"invoke name=\"([^\"]+)\">(.*?)</" + re.escape(_TOK) + r"invoke>", re.DOTALL)
_PARAM_RE = re.compile(r"<" + re.escape(_TOK) + r"parameter name=\"([^\"]+)\" string=\"(true|false)\">(.*?)</" + re.escape(_TOK) + r"parameter>", re.DOTALL)


def _parse_dsml_calls(content: str) -> list[dict]:
    """Extract inline ``<｜｜DSML｜｜invoke>`` tool calls from model content."""
    calls: list[dict] = []
    for m in _INVOKE_RE.finditer(content):
        name, body = m.group(1), m.group(2)
        args: dict = {}
        for p in _PARAM_RE.finditer(body):
            pname, is_str, pval = p.group(1), p.group(2), p.group(3).strip()
            if is_str == "false":
                try:
                    pval = int(pval)
                except ValueError:
                    pass
            args[pname] = pval
        calls.append({"name": name, "args": args, "id": f"dsml-{len(calls)}", "type": "tool_call"})
    return calls


def _strip_dsml(text: str) -> str:
    """Remove any ``<｜｜DSML｜｜>`` tool-call markup, leaving surrounding prose."""
    text = _DSML_BLOCK_RE.sub("", text)
    return _DSML_TAG_RE.sub("", text).strip()


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
    "Summarize findings in one paragraph. "
    "Your output goes to Discord, which does not render markdown tables or "
    "# headings. Use **bold** labels with bullet points instead of tables."
)

# Incident investigations return a concise ranked root-cause report with a
# suggested fix per hypothesis. The report stays informational — actual
# remediation stays human-gated via the Remediate button (a separate workflow),
# so the operator decides what to execute.
INCIDENT_SYSTEM_PROMPT = SYSTEM_PROMPT + (
    " Keep the report tight and scannable. Lead with the affected container(s) "
    "and a one-sentence root cause. Then 2-3 ranked root-cause hypotheses "
    "(most likely first) as a compact list; for each: a one-line claim, the "
    "single strongest piece of evidence (a specific metric value, log line, "
    "or container state), and a one-line concrete fix an operator could apply "
    "(e.g. restart the container, re-add it to the scrape network, fix the "
    "scrape address). Note weak evidence explicitly. Do not execute any fix — "
    "remediation stays human-gated via the Remediate button."
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
    kind: str = "ask",
    history: list[dict] | None = None,
):
    """Async generator yielding events from the bounded tool-calling loop.

    One source of truth for the Discord path (collects the final ``done`` event)
    and the SSE path (streams events to the web UI). Event types: ``tool_call``,
    ``tool_result``, ``done``.
    """
    from agent.metrics import (
        INVESTIGATION_DURATION,
        INVESTIGATION_TOTAL,
        LLM_CALL_DURATION,
        LLM_CALL_TOTAL,
        TOOL_CALL_DURATION,
        TOOL_CALL_TOTAL,
        TOOL_STEPS,
    )
    by_name = {t.name: t for t in tools}
    llm = get_llm().bind_tools(tools)
    # Force the first call to use a tool: without this, a model whose prompt
    # already narrates the ground truth (e.g. a task's symptom text) answers
    # straight from the prompt instead of verifying it, skipping the loop
    # entirely at step 0. Every real task starts from list_services, so a
    # forced first call costs nothing on the path that was already correct.
    llm_forced = get_llm().bind_tools(tools, tool_choice="required")
    messages = [SystemMessage(system_prompt)]
    for turn in (history or [])[-10:]:
        role, content = turn.get("role"), turn.get("content")
        if role == "user" and content:
            messages.append(HumanMessage(content))
        elif role == "assistant" and content:
            messages.append(AIMessage(content))
    messages.append(HumanMessage(prompt))

    ai = None
    total_steps = 0
    pending: list[dict] | None = None  # tool calls carried over from the previous turn
    t0 = time.monotonic()
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
             "n_llm_calls": 0, "n_tool_calls": 0, "llm_time_s": 0.0,
             "tool_time_s": 0.0,
             "cache_read_tokens": 0, "cache_creation_tokens": 0,
             "time_to_first_token_s": 0.0}

    def _acc(ai_msg):
        um = getattr(ai_msg, "usage_metadata", None) or {}
        usage["prompt_tokens"] += int(um.get("input_tokens", 0))
        usage["completion_tokens"] += int(um.get("output_tokens", 0))
        usage["total_tokens"] += int(um.get("total_tokens", 0))
        # OpenAI prompt-caching detail (langchain-openai surfaces it as
        # input_token_details / output_token_details). 0 when the backend has
        # no caching (self-hosted vLLM) — the aggregator treats 0 as n/a.
        din = um.get("input_token_details") or {}
        dout = um.get("output_token_details") or {}
        usage["cache_read_tokens"] += int(din.get("cache_read", 0))
        usage["cache_creation_tokens"] += int(din.get("cache_creation", 0))
        usage["n_llm_calls"] += 1

    for step in range(settings.max_tool_steps):
        total_steps = step + 1
        llm_start = time.monotonic()
        ai = await (llm_forced if step == 0 else llm).ainvoke(messages)
        dt = time.monotonic() - llm_start
        LLM_CALL_DURATION.labels(kind="agentic").observe(dt)
        LLM_CALL_TOTAL.labels(kind="agentic").inc()
        _acc(ai)
        usage["llm_time_s"] += dt
        if usage["n_llm_calls"] == 1:
            usage["time_to_first_token_s"] = dt
        messages.append(ai)
        # DeepSeek occasionally emits tool calls inline as <｜｜DSML｜｜> XML in
        # ``content`` instead of the structured ``tool_calls`` field. Fall back to
        # parsing them so the calls still execute and the loop doesn't end early
        # with raw XML as the "summary".
        pending = ai.tool_calls or _parse_dsml_calls(ai.content or "")
        if not pending:
            break

        for call in pending:
            name = call.get("name")
            args = call.get("args") or {}
            tool_id = call.get("id", "call")
            if name not in by_name:
                continue
            logger.info("Tool call: %s(%s)", name, args)
            yield {"type": "tool_call", "step": step, "name": name, "args": args}
            usage["n_tool_calls"] += 1
            try:
                tool_start = time.monotonic()
                out = await by_name[name].ainvoke(args)
                _tool_duration = time.monotonic() - tool_start
                usage["tool_time_s"] += _tool_duration
                TOOL_CALL_TOTAL.labels(tool=name, status="ok").inc()
                TOOL_CALL_DURATION.labels(tool=name).observe(_tool_duration)
            except Exception as exc:
                out = f"tool error: {exc}"
                _tool_duration = 0.0
                TOOL_CALL_TOTAL.labels(tool=name, status="error").inc()
            messages.append(ToolMessage(str(out)[:4000], tool_call_id=tool_id))
            yield {"type": "tool_result", "step": step, "name": name,
                   "result": str(out)[:2000], "duration_s": round(_tool_duration, 3)}

    # Step cap reached with pending tool calls: ask the tool-less LLM to
    # synthesize the evidence gathered so far into prose. Without this nudge the
    # model keeps trying to call tools and emits raw <｜｜DSML｜｜> XML (no tools are
    # bound, so it can't use the structured field), which would leak into the
    # summary. The explicit instruction makes it produce ranked hypotheses.
    if ai and pending:
        messages.append(HumanMessage(
            "You have used your tool budget. Using only the evidence gathered above, "
            "write your ranked root-cause hypotheses as concise prose. Do not call "
            "tools and do not emit any XML or tool-call markup."
        ))
        llm_start = time.monotonic()
        ai = await get_llm().ainvoke(messages)
        dt = time.monotonic() - llm_start
        LLM_CALL_DURATION.labels(kind="fallback").observe(dt)
        LLM_CALL_TOTAL.labels(kind="fallback").inc()
        _acc(ai)
        usage["llm_time_s"] += dt

    content = _strip_dsml((ai.content if ai else "") or "")
    if not content:
        content = "No summary produced."
    INVESTIGATION_DURATION.labels(kind=kind).observe(time.monotonic() - t0)
    TOOL_STEPS.labels(kind=kind).observe(total_steps)
    INVESTIGATION_TOTAL.labels(kind=kind, status="ok").inc()
    usage["n_turns"] = total_steps
    usage["time_to_last_token_s"] = time.monotonic() - t0
    yield {"type": "done", "content": content, "usage": usage}


async def run_agentic_investigation(
    prompt: str,
    *,
    system_prompt: str = SYSTEM_PROMPT,
    tools: list = TOOLS,
    kind: str = "ask",
    history: list[dict] | None = None,
) -> str:
    """Bounded tool-calling loop. Returns the LLM's final answer or a fallback message.

    Thin collector over :func:`run_agentic_investigation_stream` so the Discord path
    and the SSE path share one loop implementation. ``history`` carries prior
    turns (``{"role": "user"|"assistant", "content": ...}``) which the stream
    loop renders as real ``HumanMessage``/``AIMessage`` turns before the prompt.
    """
    content, _ = await run_agentic_investigation_with_usage(
        prompt, system_prompt=system_prompt, tools=tools, kind=kind, history=history
    )
    return content


async def run_agentic_investigation_with_usage(
    prompt: str,
    *,
    system_prompt: str = SYSTEM_PROMPT,
    tools: list = TOOLS,
    kind: str = "ask",
    history: list[dict] | None = None,
) -> tuple[str, dict]:
    """Like :func:`run_agentic_investigation` but also returns the accumulated
    token/latency usage dict from the ``done`` event (for evals/cost)."""
    usage: dict = {}
    content = "No summary produced."
    async for event in run_agentic_investigation_stream(
        prompt, system_prompt=system_prompt, tools=tools, kind=kind, history=history
    ):
        if event["type"] == "done":
            content = event["content"]
            usage = event.get("usage", {}) or {}
    return content, usage


async def run_incident_workflow(service: str, hint: str | None = None) -> dict:
    """Collect signals for a service and return an incident id and summary.

    ``hint`` is optional operator-supplied context (e.g. a task's reported
    symptom) appended to the investigation prompt so the agent investigates
    with the reported problem in mind, not just the bare service name.
    """
    prompt = f"Investigate service {service}."
    if hint:
        prompt += f" Reported symptom: {hint}"
    try:
        summary = await run_agentic_investigation(prompt, system_prompt=INCIDENT_SYSTEM_PROMPT, kind="incident")
    except Exception as exc:
        logger.warning("Agentic workflow failed for %s: %s", service, exc)
        summary = await _static_summary(service)

    if not summary or summary == "No summary produced.":
        summary = await _static_summary(service)

    incident_id = store_incident(service, summary)
    return {"incident_id": incident_id, "summary": summary}


async def run_incident_workflow_stream(service: str, hint: str | None = None):
    """Stream the incident investigation, then persist and yield the incident id at ``done``.

    Falls back to ``_static_summary`` on exception, mirroring the non-stream path, and
    emits an ``error`` event instead of raising so the SSE connection stays usable.
    ``hint`` is optional operator-supplied context appended to the prompt.
    """
    prompt = f"Investigate service {service}."
    if hint:
        prompt += f" Reported symptom: {hint}"
    try:
        async for event in run_agentic_investigation_stream(
            prompt, system_prompt=INCIDENT_SYSTEM_PROMPT, kind="incident"
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


async def run_ask_workflow_stream(question: str, history: list[dict] | None = None):
    """Stream a free-form agentic answer; does not persist an incident."""
    try:
        async for event in run_agentic_investigation_stream(question, history=history):
            yield event
    except Exception as exc:
        logger.warning("Ask workflow stream failed: %s", exc)
        yield {"type": "error", "message": str(exc)}


async def run_scoped_investigation(prompt: str) -> tuple[str, str]:
    """Run the agentic loop for a scoped command (``/metrics`` / ``/logs``) and
    return ``(summary, raw_results)``.

    ``summary`` is the model's final narrative; ``raw_results`` is the
    concatenated tool outputs (PromQL/LogQL results, container state) for the
    ``raw`` opt-out. The loop is the same one ``/ask`` uses, so the model
    resolves the service name (typos, separators) via ``list_services``,
    discovers the available metrics/labels, and writes its own PromQL/LogQL
    rather than running a hardcoded query.
    """
    summary = ""
    raw_parts: list[str] = []
    async for event in run_ask_workflow_stream(prompt):
        if event["type"] == "tool_result":
            raw_parts.append(f"### {event['name']}\n{event['result']}")
        elif event["type"] == "done":
            summary = event.get("content", "") or ""
        elif event["type"] == "error":
            summary = f"Agentic loop failed: {event.get('message', '')}"
    return summary, "\n\n".join(raw_parts)


async def run_ask_workflow(question: str, history: list[dict] | None = None) -> str:
    """Free-form agentic answer; does not persist an incident.

    ``history`` carries prior conversational turns so the agent remembers the
    ongoing conversation; the current question is appended as the final turn.
    """
    try:
        return await run_agentic_investigation(question, history=history)
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
