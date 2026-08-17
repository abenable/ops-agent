"""Agentic investigation loop: the LLM reasons over the read-only tools.

A manual tool-calling loop over ``langchain-core`` messages — no agent
framework dependency. The model calls tools (Docker, Prometheus, Loki) until
it has enough evidence to answer, or until ``max_tool_steps`` is hit, in which
case it gets one final no-tools call to summarize what it found.
"""

import logging

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from agent.bot.summarize import discordify
from agent.config.settings import settings
from agent.llm.client import get_llm
from agent.tools import ALL_TOOLS

logger = logging.getLogger(__name__)

_TOOLS_BY_NAME = {t.name: t for t in ALL_TOOLS}

_SYSTEM_PROMPT = """You are Oracle, a terse infrastructure-operations assistant for the Marconi lab.
You answer questions about the lab's Docker services using ONLY the read-only
tools available to you (container status/logs, Prometheus metrics, Loki logs).

Rules:
- Use list_services first when you are unsure of an exact service name.
- Prefer evidence over guessing: check container state, then logs, then metrics.
- You are read-only. Never suggest you can restart or change anything yourself;
  recommend the action for a human operator instead.
- Answer in Discord markdown: **bold** section headers, bullet lists, backticks
  around container names and values. Do NOT use # headings or tables.
- End every investigation with a likely cause and recommended next steps.
- Be concise; this is a chat channel, not a report.
"""

_REPORT_TEMPLATE = """Write a structured incident report for the service `{service}`.

Use the tools to check its container state, recent logs, and metrics before
writing anything. Then answer with exactly these sections:

**Summary** — one or two sentences.
**What happened** — observed behavior and timeline.
**Evidence** — the log lines / metric values that back it up.
**Likely cause** — your best-supported hypothesis.
**Recommended next steps** — actions for a human operator (you are read-only).

If the service looks healthy, say so plainly in the Summary and keep the rest short."""


def _text(content) -> str:
    """Coerce an LLM message content (str or content-block list) to plain text."""
    if isinstance(content, str):
        return content.strip()
    return "".join(
        block.get("text", "") for block in content if isinstance(block, dict)
    ).strip()


async def _run_loop(question: str) -> str:
    """Run the tool-calling loop and return the model's final answer."""
    messages: list = [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=question)]
    llm = get_llm().bind_tools(ALL_TOOLS)

    for _ in range(settings.max_tool_steps):
        ai = await llm.ainvoke(messages)
        messages.append(ai)
        if not ai.tool_calls:
            return _text(ai.content)
        for call in ai.tool_calls:
            tool = _TOOLS_BY_NAME.get(call["name"])
            logger.info("tool call: %s(%s)", call["name"], call["args"])
            if tool is None:
                output = f"(unknown tool '{call['name']}')"
            else:
                try:
                    output = await tool.ainvoke(call["args"])
                except Exception as exc:
                    output = f"(tool '{call['name']}' failed: {exc})"
            messages.append(ToolMessage(content=str(output), tool_call_id=call["id"]))

    # Tool budget exhausted: one final call without tools to summarize findings.
    logger.info("tool budget exhausted (%d steps); requesting final summary", settings.max_tool_steps)
    messages.append(
        HumanMessage(
            content="You have used the tool budget. Summarize what you found so far, "
            "state the likely cause and next steps, and note what you could not check."
        )
    )
    final = await get_llm().ainvoke(messages)
    return _text(final.content)


async def investigate(question: str) -> str:
    """Answer a free-form ops question with the tool-calling loop."""
    try:
        answer = await _run_loop(question)
    except Exception as exc:
        logger.exception("investigation failed")
        return f"Investigation failed: {exc}"
    if not answer:
        return "The model returned an empty answer."
    return discordify(answer)


async def report(service: str) -> str:
    """Generate a structured incident report for one service."""
    return await investigate(_REPORT_TEMPLATE.format(service=service))
