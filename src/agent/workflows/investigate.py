"""Free-form ops investigation: a question put to the Oracle agent."""

import asyncio
import logging
import time

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.types import Command

from agent.agent import get_agent
from agent.bot.summarize import _joined, _text, discordify
from agent.memory import thread_config

logger = logging.getLogger(__name__)

_INVESTIGATION_TIMEOUT = 60.0

_DENIED = (
    "The person reviewing tool calls denied this one, so it did not run. It is not an error "
    "or a permissions problem. Do not retry it unless they ask; answer from the evidence you have "
    "and say what you could not check."
)


def _tools_used(messages) -> str:
    """Tool names called since the last question; earlier turns share the thread."""
    last_human = max(
        (i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=-1
    )
    names = [
        call["name"]
        for m in messages[last_human + 1 :]
        for call in getattr(m, "tool_calls", None) or []
    ]
    return ", ".join(names) or "none"


def _key(message) -> tuple | None:
    """Identity of a message across stream updates; ``None`` when it has none yet."""
    if isinstance(message, ToolMessage):
        return ("tool", message.tool_call_id)
    if isinstance(message, AIMessage) and message.id:
        return ("ai", message.id)
    return None


async def investigate(question: str, thread_id: str | None = None) -> str:
    """Answer a free-form ops question."""
    started = time.monotonic()
    logger.info("investigating [thread=%s]: %s", thread_id or "-", question[:200])
    try:
        agent = await get_agent()
        final = await asyncio.wait_for(
            agent.ainvoke(
                {"messages": [HumanMessage(content=question)]},
                thread_config(thread_id),
            ),
            timeout=_INVESTIGATION_TIMEOUT,
        )
    except TimeoutError:
        logger.warning(
            "investigation timed out after %.0fs [thread=%s]",
            _INVESTIGATION_TIMEOUT,
            thread_id or "-",
        )
        return f"Investigation timed out after {_INVESTIGATION_TIMEOUT:.0f}s."
    except Exception as exc:
        logger.exception("investigation failed")
        return f"Investigation failed: {exc}"
    answer = _text(final["messages"][-1].content)
    logger.info(
        "investigation done in %.1fs [thread=%s] tools=%s answer=%d chars",
        time.monotonic() - started,
        thread_id or "-",
        _tools_used(final["messages"]),
        len(answer),
    )
    if not answer:
        return "The model returned an empty answer."
    return discordify(answer)


class _Refused(Exception):
    """The thread is (or is not) paused on tool calls, so this request cannot run."""


def _awaiting(state) -> list[dict]:
    """Tool calls a paused run is holding for a person's decision."""
    if not state.interrupts:
        return []
    messages = state.values.get("messages", [])
    answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
    last = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
    return [c for c in (last.tool_calls if last else []) if c["id"] not in answered]


async def stream_investigation(
    question: str | None,
    thread_id: str | None = None,
    *,
    tools: list[str] | None = None,
    approval: bool = False,
    decisions: dict[str, bool] | None = None,
):
    """Answer like ``investigate``, yielding ``(event, data)`` pairs as the agent works.

    Events: ``token`` (answer text as it is generated), ``tool_call``, ``tool_result``,
    ``approval_required`` (with ``approval``, the run paused before these tool calls ran),
    ``error`` (the same messages ``investigate`` returns on failure), then ``done``.

    ``tools`` narrows the agent to those tool names. To resume a paused run, pass
    ``decisions`` (tool call id -> approved) instead of a question; a call left out is rejected.
    """
    config = thread_config(thread_id)
    thread = config["configurable"]["thread_id"]
    logger.info("streaming investigation [thread=%s]: %s", thread, (question or "resuming")[:200])
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _INVESTIGATION_TIMEOUT
    wrote_text = paused = False
    stream = None
    try:
        agent = await get_agent(tools, approval=approval)
        state = await agent.aget_state(config)
        waiting = _awaiting(state)
        if decisions is not None and not waiting:
            raise _Refused("No tool calls are waiting for approval.")
        if decisions is None and waiting:
            raise _Refused("Approve or deny the pending tool calls first.")
        payload = (
            Command(resume={"decisions": [
                {"type": "approve"} if decisions.get(c["id"]) else {"type": "reject", "message": _DENIED}
                for c in waiting
            ]})
            if decisions is not None
            else {"messages": [HumanMessage(content=question)]}
        )
        seen = {_key(m) for m in state.values.get("messages", [])} - {None}
        streamed: set[str] = set()
        stream = agent.astream(payload, config, stream_mode=["messages", "updates"])
        while True:
            try:
                mode, data = await asyncio.wait_for(anext(stream), deadline - loop.time())
            except StopAsyncIteration:
                break
            if mode == "messages":
                chunk, meta = data
                if (
                    meta.get("langgraph_node") == "model"
                    and isinstance(chunk, AIMessageChunk)
                    and (delta := _joined(chunk.content))
                ):
                    streamed.add(chunk.id)
                    wrote_text = True
                    yield "token", {"id": chunk.id, "text": delta}
                continue
            if "__interrupt__" in (data or {}):
                paused = True
                continue
            for update in (data or {}).values():
                messages = update.get("messages", []) if isinstance(update, dict) else []
                for message in messages if isinstance(messages, list) else [messages]:
                    key = _key(message)
                    if key in seen:
                        continue
                    if key:
                        seen.add(key)
                    if isinstance(message, ToolMessage):
                        yield "tool_result", {
                            "id": message.tool_call_id,
                            "name": message.name,
                            "content": _text(message.content),
                            "status": message.status,
                        }
                    elif isinstance(message, AIMessage):
                        if message.id not in streamed and (text := _text(message.content)):
                            wrote_text = True
                            yield "token", {"id": message.id, "text": text}
                        for call in message.tool_calls:
                            yield "tool_call", {
                                "id": call["id"],
                                "name": call["name"],
                                "args": call["args"],
                            }
        if paused:
            waiting = _awaiting(await agent.aget_state(config))
            yield "approval_required", {
                "tool_calls": [{"id": c["id"], "name": c["name"], "args": c["args"]} for c in waiting]
            }
        elif not wrote_text:
            yield "error", {"message": "The model returned an empty answer."}
    except _Refused as exc:
        yield "error", {"message": str(exc)}
    except TimeoutError:
        logger.warning(
            "investigation timed out after %.0fs [thread=%s]", _INVESTIGATION_TIMEOUT, thread
        )
        yield "error", {"message": f"Investigation timed out after {_INVESTIGATION_TIMEOUT:.0f}s."}
    except Exception as exc:
        logger.exception("investigation failed")
        yield "error", {"message": f"Investigation failed: {exc}"}
    finally:
        if stream is not None:
            await stream.aclose()
    yield "done", {"thread_id": thread}
