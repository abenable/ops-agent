"""Free-form ops investigation: the Oracle persona bound to every read-only
tool, run through the generic agent engine (``agent.engine``).
"""

import logging

from agent.bot.summarize import discordify
from agent.engine import run as run_agent
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

_BUDGET_PROMPT = (
    "You have used the tool budget. Summarize what you found so far, "
    "state the likely cause and next steps, and note what you could not check."
)


async def investigate(question: str, thread_id: str | None = None) -> str:
    """Answer a free-form ops question.

    Callers that pass a stable ``thread_id`` (a Discord channel id) get a
    conversation; callers that omit it get a one-shot thread.
    """
    try:
        answer = await run_agent(
            question,
            tools_by_name=_TOOLS_BY_NAME,
            system_prompt=_SYSTEM_PROMPT,
            budget_prompt=_BUDGET_PROMPT,
            thread_id=thread_id,
        )
    except Exception as exc:
        logger.exception("investigation failed")
        return f"Investigation failed: {exc}"
    if not answer:
        return "The model returned an empty answer."
    return discordify(answer)
