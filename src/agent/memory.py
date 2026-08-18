"""Agent memory: the conversation state the investigation loop carries.

Short-term memory is a LangGraph checkpointer keyed by ``thread_id`` — one
thread per Discord channel. It lives here, not inside ``investigate.py``, so
anything else (another loop, an eval notebook) can share the same threads,
read one back, or drop it.

Checkpoints are written to the same SQLite file as the watch list, so a thread
survives a bot restart and is readable from any process — a digest posted by a
one-off script seeds the same thread the running bot later answers in.

Note what this is *not*: memory of one conversation, replayed per ``thread_id``.
There is no cross-thread recall, and ``window()`` still trims the oldest turns
out of a long thread, so a large seeded report is the first thing evicted.
"""

from contextlib import AsyncExitStack
from uuid import uuid4

from langchain_core.messages import BaseMessage, trim_messages
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from agent.config.settings import DB_PATH, settings

_CHECKPOINTER: AsyncSqliteSaver | None = None
_STACK: AsyncExitStack | None = None


async def checkpointer():
    """The process-wide saver, opened on first use inside the running loop.

    Not a module-level constant: ``AsyncSqliteSaver`` owns an ``aiosqlite``
    connection bound to the loop it is opened in, so it has to be built inside
    one. Tests inject an ``InMemorySaver`` by setting ``_CHECKPOINTER``, which
    is returned as-is.
    """
    global _CHECKPOINTER, _STACK
    if _CHECKPOINTER is None:
        _STACK = AsyncExitStack()
        _CHECKPOINTER = await _STACK.enter_async_context(
            AsyncSqliteSaver.from_conn_string(str(DB_PATH))
        )
        # Create the tables up front: adelete_thread (/reset) is the one entry
        # point that does not create them on demand.
        await _CHECKPOINTER.setup()
    return _CHECKPOINTER


async def close_memory() -> None:
    """Close the checkpointer's connection. Must be called before the loop ends.

    aiosqlite runs the connection on a worker thread that keeps blocking on its
    queue after the loop closes, so skipping this hangs the process at exit
    rather than leaking quietly.
    """
    global _CHECKPOINTER, _STACK
    if _STACK is not None:
        await _STACK.aclose()
    _CHECKPOINTER = _STACK = None


def thread_config(thread_id: str | None = None, **extra) -> RunnableConfig:
    """Config for one conversation thread; omit ``thread_id`` for a one-shot.

    ``extra`` is merged into ``configurable`` for the per-run objects graph
    nodes need — the bound LLM, for instance.
    """
    return {
        "configurable": {"thread_id": thread_id or str(uuid4()), **extra},
        # A model turn costs two graph steps (model, then tools).
        "recursion_limit": 2 * settings.max_tool_steps,
    }


def window(messages: list[BaseMessage]) -> list[BaseMessage]:
    """The tail of a thread that still fits in the model's context.

    A remembered thread grows without bound, so trim before every model call.
    ``start_on``/``end_on`` keep each AIMessage's tool_calls together with their
    ToolMessages — splitting that pair is a 400 from an OpenAI-compatible API.
    """
    return trim_messages(
        messages,
        max_tokens=settings.max_context_tokens,
        token_counter="approximate",
        start_on="human",
        end_on=("human", "tool"),
    )


async def history(thread_id: str) -> list[BaseMessage]:
    """Every message remembered for a thread; empty if it has never run."""
    saver = await checkpointer()
    checkpoint = await saver.aget(thread_config(thread_id))
    if checkpoint is None:
        return []
    return checkpoint["channel_values"].get("messages", [])


async def forget(thread_id: str) -> None:
    """Drop a thread's conversation, so the next question starts clean."""
    saver = await checkpointer()
    await saver.adelete_thread(thread_id)
