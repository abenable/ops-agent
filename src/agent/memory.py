"""Agent memory: conversation state checkpointed per ``thread_id``."""

import asyncio
from contextlib import AsyncExitStack
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from agent.config.settings import MEMORY_DB_PATH

_CHECKPOINTER: AsyncSqliteSaver | None = None
_STACK: AsyncExitStack | None = None
_OPENING: asyncio.Lock | None = None


async def checkpointer():
    """The process-wide saver, opened on first use inside the running loop.

    Concurrent first callers (the API serving parallel requests) share one open;
    the saver is published only once its setup has finished.
    """
    global _CHECKPOINTER, _STACK, _OPENING
    if _CHECKPOINTER is None:
        _OPENING = _OPENING or asyncio.Lock()
        async with _OPENING:
            if _CHECKPOINTER is None:
                stack = AsyncExitStack()
                saver = await stack.enter_async_context(
                    AsyncSqliteSaver.from_conn_string(str(MEMORY_DB_PATH))
                )
                await saver.setup()
                _STACK, _CHECKPOINTER = stack, saver
    return _CHECKPOINTER


async def close_memory() -> None:
    """Close the checkpointer's connection. Must be called before the loop ends."""
    global _CHECKPOINTER, _STACK, _OPENING
    if _STACK is not None:
        await _STACK.aclose()
    _CHECKPOINTER = _STACK = _OPENING = None


def thread_config(thread_id: str | None = None) -> RunnableConfig:
    """Config for one conversation thread; omit ``thread_id`` for a one-shot."""
    return {"configurable": {"thread_id": thread_id or str(uuid4())}}

