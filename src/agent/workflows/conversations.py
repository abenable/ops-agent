"""Stored conversations read back from agent memory, for browsing and transcript review."""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.agent import get_agent
from agent.memory import checkpointer, thread_config
from agent.workflows.investigate import _awaiting, _text


def _messages(item) -> list:
    return item.checkpoint["channel_values"].get("messages", [])


def _is_summary(message) -> bool:
    return message.additional_kwargs.get("lc_source") == "summarization"


def _title(messages: list) -> str:
    for message in messages:
        if isinstance(message, HumanMessage) and not _is_summary(message):
            return _text(message.content)[:200]
    return ""


def _root(item) -> bool:
    return item.config["configurable"].get("checkpoint_ns", "") == ""


async def list_threads() -> list[dict]:
    """Every stored conversation, most recently active first."""
    # ponytail: deserializes every checkpoint; move to SQL paging once history is large
    threads: dict[str, dict] = {}
    async for item in (await checkpointer()).alist(None):
        if not _root(item):
            continue
        thread_id = item.config["configurable"]["thread_id"]
        at = item.checkpoint["ts"]
        if thread_id in threads:
            threads[thread_id]["started_at"] = min(threads[thread_id]["started_at"], at)
            continue
        messages = _messages(item)
        threads[thread_id] = {
            "thread_id": thread_id,
            "title": _title(messages),
            "started_at": at,
            "updated_at": at,
            "turns": sum(isinstance(m, HumanMessage) and not _is_summary(m) for m in messages),
            "messages": len(messages),
        }
    return sorted(threads.values(), key=lambda t: t["updated_at"], reverse=True)


def _record(message, at: str | None) -> dict:
    record = {
        "id": message.id,
        "type": "summary" if _is_summary(message) else message.type,
        "content": _text(message.content),
        "at": at,
    }
    if isinstance(message, AIMessage):
        record["tool_calls"] = [
            {"id": c["id"], "name": c["name"], "args": c["args"]} for c in message.tool_calls
        ]
        record["usage"] = message.usage_metadata
    if isinstance(message, ToolMessage):
        record |= {"tool_call_id": message.tool_call_id, "name": message.name, "status": message.status}
    return record


async def read_thread(thread_id: str) -> list[dict] | None:
    """Every message the thread ever held, in order, stamped with when it first appeared.

    Replays the checkpoint history rather than the latest state, so turns that
    summarization later folded away still show up.
    """
    history = [
        item
        async for item in (await checkpointer()).alist(thread_config(thread_id))
        if _root(item)
    ]
    if not history:
        return None
    first_seen: dict[str, tuple] = {}
    for item in reversed(history):
        for message in _messages(item):
            if message.id and message.id not in first_seen:
                first_seen[message.id] = (message, item.checkpoint["ts"])
    return [_record(message, at) for message, at in first_seen.values()]


async def awaiting_approval(thread_id: str) -> list[str]:
    """Ids of the tool calls a paused run in this thread is holding for a decision."""
    agent = await get_agent(approval=True)
    return [c["id"] for c in _awaiting(await agent.aget_state(thread_config(thread_id)))]
