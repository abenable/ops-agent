"""The generic agent engine: a LangGraph tool-calling loop with no opinion on
which tools or system prompt it runs with.

Two nodes — the model, and the tools it asks for — looping until it answers or
the tool budget runs out, in which case it gets one final no-tools call to
summarize what it found. Conversation state lives in ``agent.memory``,
checkpointed per ``thread_id``, so a Discord channel keeps its context across
messages and loses it when the bot restarts.

Callers (``agent.workflows.*``) pick the tools and prompts per call via
``run()`` — this module never imports ``agent.tools`` or hardcodes a persona,
so a workflow that wants a narrower tool set doesn't touch the loop itself.
"""

import logging

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, MessagesState, StateGraph

from agent.config.settings import settings
from agent.llm.client import get_llm
from agent.memory import CHECKPOINTER, thread_config, window

logger = logging.getLogger(__name__)


def _text(content) -> str:
    """Coerce an LLM message content (str or content-block list) to plain text."""
    if isinstance(content, str):
        return content.strip()
    return "".join(
        block.get("text", "") for block in content if isinstance(block, dict)
    ).strip()


async def _call_model(state: MessagesState, config: RunnableConfig) -> dict:
    """Ask the model what to do next. The client and system prompt are built
    once per run and handed down through the config, not rebuilt each turn."""
    llm = config["configurable"]["llm"]
    system_prompt = config["configurable"]["system_prompt"]
    prompt = [SystemMessage(content=system_prompt), *window(state["messages"])]
    return {"messages": [await llm.ainvoke(prompt)]}


async def _call_tools(state: MessagesState, config: RunnableConfig) -> dict:
    """Run every tool call the model made this turn."""
    tools_by_name = config["configurable"]["tools_by_name"]
    results = []
    for call in state["messages"][-1].tool_calls:
        tool = tools_by_name.get(call["name"])
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


async def _summarize_after_budget(config: dict, budget_prompt: str) -> str:
    """One last no-tools call over the checkpointed thread once the budget is gone."""
    logger.info("tool budget exhausted (%d steps); requesting final summary", settings.max_tool_steps)
    system_prompt = config["configurable"]["system_prompt"]
    state = await _GRAPH.aget_state(config)
    messages = [
        SystemMessage(content=system_prompt),
        *window(state.values["messages"]),
        HumanMessage(content=budget_prompt),
    ]
    return _text((await get_llm().ainvoke(messages)).content)


async def run(
    question: str,
    *,
    tools_by_name: dict,
    system_prompt: str,
    budget_prompt: str,
    thread_id: str | None = None,
) -> str:
    """Drive the graph to an answer on one thread with the given tools/prompts.

    ``tools_by_name`` is taken as the caller built it (name -> tool), not
    rebuilt from a list here, so a workflow's own dict — and whatever it puts
    in it, real tool or test fake — is exactly what the loop looks up by.

    Callers that pass a stable ``thread_id`` (a Discord channel id) get a
    conversation; callers that omit it get a one-shot thread. The recursion
    limit in ``thread_config`` is the tool budget; hitting it raises and we
    fall back to a summary of whatever the thread accumulated. Exceptions
    otherwise propagate — it's up to the caller whether a failure means an
    error message or something else.
    """
    config = thread_config(
        thread_id,
        llm=get_llm().bind_tools(list(tools_by_name.values())),
        tools_by_name=tools_by_name,
        system_prompt=system_prompt,
    )
    try:
        final = await _GRAPH.ainvoke({"messages": [HumanMessage(content=question)]}, config)
    except GraphRecursionError:
        return await _summarize_after_budget(config, budget_prompt)
    return _text(final["messages"][-1].content)


async def seed(thread_id: str, content: str) -> None:
    """Pre-load a thread's memory with one message before any real turn.

    For content posted by something other than a model turn — a scheduled
    report, say — so a later mention in that thread has it as context.
    Recorded as a ``HumanMessage``, not an ``AIMessage``: ``window()`` trims
    every prompt with ``start_on="human"``, which silently drops a lone
    leading ``AIMessage`` before it ever reaches the model — so a
    ``HumanMessage`` is the only type guaranteed to survive as the seed of a
    fresh thread.
    """
    await _GRAPH.aupdate_state(
        thread_config(thread_id), {"messages": [HumanMessage(content=content)]}, as_node=START
    )
