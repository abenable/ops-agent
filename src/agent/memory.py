"""Agent memory: the conversation state the investigation loop carries.

Short-term memory is a LangGraph checkpointer keyed by ``thread_id`` — one
thread per Discord channel. It lives here, not inside ``investigate.py``, so
anything else (another loop, an eval notebook) can share the same threads,
read one back, or drop it.

In-memory means in-memory: threads die with the process. Swap ``CHECKPOINTER``
for a ``SqliteSaver`` (needs ``langgraph-checkpoint-sqlite``) if they should
survive a restart — nothing else in this module changes.
"""

from uuid import uuid4

from langchain_core.messages import BaseMessage, trim_messages
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver

from agent.config.settings import settings

# Shared by every graph that wants to remember a thread. Compile with
# ``graph.compile(checkpointer=CHECKPOINTER)``.
CHECKPOINTER = InMemorySaver()


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
    checkpoint = await CHECKPOINTER.aget(thread_config(thread_id))
    if checkpoint is None:
        return []
    return checkpoint["channel_values"].get("messages", [])


async def forget(thread_id: str) -> None:
    """Drop a thread's conversation, so the next question starts clean."""
    await CHECKPOINTER.adelete_thread(thread_id)
