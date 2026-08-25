"""Agent memory: conversation state checkpointed per ``thread_id``."""

from contextlib import AsyncExitStack
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from agent.config.settings import MEMORY_DB_PATH

_CHECKPOINTER: AsyncSqliteSaver | None = None
_STACK: AsyncExitStack | None = None


async def checkpointer():
    """The process-wide saver, opened on first use inside the running loop."""
    global _CHECKPOINTER, _STACK
    if _CHECKPOINTER is None:
        _STACK = AsyncExitStack()
        _CHECKPOINTER = await _STACK.enter_async_context(
            AsyncSqliteSaver.from_conn_string(str(MEMORY_DB_PATH))
        )
        await _CHECKPOINTER.setup()
    return _CHECKPOINTER


async def close_memory() -> None:
    """Close the checkpointer's connection. Must be called before the loop ends."""
    global _CHECKPOINTER, _STACK
    if _STACK is not None:
        await _STACK.aclose()
    _CHECKPOINTER = _STACK = None


def thread_config(thread_id: str | None = None) -> RunnableConfig:
    """Config for one conversation thread; omit ``thread_id`` for a one-shot."""
    return {"configurable": {"thread_id": thread_id or str(uuid4())}}

