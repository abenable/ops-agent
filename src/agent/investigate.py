"""Agentic investigation: a LangGraph state machine over the read-only tools.

Two nodes — the model, and the tools it asks for — looping until it answers or
the tool budget runs out, in which case it gets one final no-tools call to
summarize what it found. Conversation state lives in ``agent.memory``,
checkpointed per ``thread_id``, so a Discord channel keeps its context across
messages and loses it when the bot restarts.
"""

import logging

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, MessagesState, StateGraph

from agent.bot.summarize import discordify
from agent.config.settings import settings
from agent.llm.client import get_llm
from agent.memory import CHECKPOINTER, thread_config, window
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

_BUDGET_PROMPT = (
    "You have used the tool budget. Summarize what you found so far, "
    "state the likely cause and next steps, and note what you could not check."
)


def _text(content) -> str:
    """Coerce an LLM message content (str or content-block list) to plain text."""
    if isinstance(content, str):
        return content.strip()
    return "".join(
        block.get("text", "") for block in content if isinstance(block, dict)
    ).strip()


async def _call_model(state: MessagesState, config: RunnableConfig) -> dict:
    """Ask the model what to do next. The client is built once per run and
    handed down through the config, not rebuilt on every turn."""
    llm = config["configurable"]["llm"]
    prompt = [SystemMessage(content=_SYSTEM_PROMPT), *window(state["messages"])]
    return {"messages": [await llm.ainvoke(prompt)]}


async def _call_tools(state: MessagesState) -> dict:
    """Run every tool call the model made this turn."""
    results = []
    for call in state["messages"][-1].tool_calls:
        tool = _TOOLS_BY_NAME.get(call["name"])
        logger.info("tool call: %s(%s)", call["name"], call["args"])
        if tool is None:
            output = f"(unknown tool '{call['name']}')"
        else:
            try:
                output = await tool.ainvoke(call["args"])
            except Exception as exc:  # noqa: BLE001 - tool can raise anything
                output = f"(tool '{call['name']}' failed: {exc})"
        results.append(ToolMessage(content=str(output), tool_call_id=call["id"]))
    return {"messages": results}


def _next_step(state: MessagesState) -> str:
    """Loop back through the tools while the model keeps asking for them."""
    return "tools" if state["messages"][-1].tool_calls else END


def _build_graph():
    graph = StateGraph(MessagesState)
    graph.add_node("model", _call_model)
    graph.add_node("tools", _call_tools)
    graph.add_edge(START, "model")
    graph.add_conditional_edges("model", _next_step, {"tools": "tools", END: END})
    graph.add_edge("tools", "model")
    return graph.compile(checkpointer=CHECKPOINTER)


_GRAPH = _build_graph()


async def _summarize_after_budget(config: dict) -> str:
    """One last no-tools call over the checkpointed thread once the budget is gone."""
    logger.info("tool budget exhausted (%d steps); requesting final summary", settings.max_tool_steps)
    state = await _GRAPH.aget_state(config)
    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        *window(state.values["messages"]),
        HumanMessage(content=_BUDGET_PROMPT),
    ]
    return _text((await get_llm().ainvoke(messages)).content)


async def _run(question: str, thread_id: str | None) -> str:
    """Drive the graph to an answer on one thread.

    The recursion limit in ``thread_config`` is the tool budget; hitting it
    raises and we fall back to a summary of whatever the thread accumulated.
    """
    config = thread_config(thread_id, llm=get_llm().bind_tools(ALL_TOOLS))
    try:
        final = await _GRAPH.ainvoke({"messages": [HumanMessage(content=question)]}, config)
    except GraphRecursionError:
        return await _summarize_after_budget(config)
    return _text(final["messages"][-1].content)


async def investigate(question: str, thread_id: str | None = None) -> str:
    """Answer a free-form ops question.

    Callers that pass a stable ``thread_id`` (a Discord channel id) get a
    conversation; callers that omit it get a one-shot thread.
    """
    try:
        answer = await _run(question, thread_id)
    except Exception as exc:
        logger.exception("investigation failed")
        return f"Investigation failed: {exc}"
    if not answer:
        return "The model returned an empty answer."
    return discordify(answer)


async def report(service: str) -> str:
    """Generate a structured incident report for one service (always one-shot)."""
    return await investigate(_REPORT_TEMPLATE.format(service=service))
