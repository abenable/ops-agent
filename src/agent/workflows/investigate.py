"""Free-form ops investigation: a question put to the Oracle agent."""

import asyncio
import logging
import time

from langchain_core.messages import HumanMessage

from agent.agent import get_agent
from agent.bot.summarize import discordify
from agent.memory import thread_config

logger = logging.getLogger(__name__)

_INVESTIGATION_TIMEOUT = 60.0


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


def _text(content) -> str:
    """Coerce an LLM message content (str or content-block list) to plain text."""
    if isinstance(content, str):
        return content.strip()
    return "".join(
        block.get("text", "") for block in content if isinstance(block, dict)
    ).strip()


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
