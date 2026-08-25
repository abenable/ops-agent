"""Free-form ops investigation: a question put to the Oracle agent."""

import logging

from langchain_core.messages import HumanMessage

from agent.agent import get_agent
from agent.bot.summarize import discordify
from agent.memory import thread_config

logger = logging.getLogger(__name__)


def _text(content) -> str:
    """Coerce an LLM message content (str or content-block list) to plain text."""
    if isinstance(content, str):
        return content.strip()
    return "".join(
        block.get("text", "") for block in content if isinstance(block, dict)
    ).strip()


async def investigate(question: str, thread_id: str | None = None) -> str:
    """Answer a free-form ops question."""
    try:
        agent = await get_agent()
        final = await agent.ainvoke(
            {"messages": [HumanMessage(content=question)]},
            thread_config(thread_id),
        )
    except Exception as exc:
        logger.exception("investigation failed")
        return f"Investigation failed: {exc}"
    answer = _text(final["messages"][-1].content)
    if not answer:
        return "The model returned an empty answer."
    return discordify(answer)
