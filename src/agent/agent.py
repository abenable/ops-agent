"""Builds and caches the Oracle agent shared by every workflow."""

from langchain.agents import create_agent
from langchain.agents.middleware import (
    SummarizationMiddleware,
    ToolCallLimitMiddleware,
    ToolErrorMiddleware,
)

from agent.config.settings import settings
from agent.memory import checkpointer
from agent.tools import ALL_TOOLS

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

_AGENT: tuple | None = None


async def _tool_error(exc: Exception, request) -> str:
    """Return a tool failure to the model as a ToolMessage so it can react."""
    return f"(tool '{request.tool_call['name']}' failed: {exc})"


async def get_agent():
    """The Oracle agent, rebuilt only if the checkpointer changes."""
    global _AGENT
    saver = await checkpointer()
    if _AGENT is None or _AGENT[0] is not saver:
        _AGENT = (
            saver,
            create_agent(
                model=settings.model_id,
                tools=list(_TOOLS_BY_NAME.values()),
                system_prompt=_SYSTEM_PROMPT,
                middleware=[
                    ToolCallLimitMiddleware(
                        run_limit=settings.max_tool_steps,
                        exit_behavior="end",
                    ),
                    ToolErrorMiddleware(aon_error=_tool_error),
                    SummarizationMiddleware(
                        model=settings.summarizer_model_id,
                        trigger=("tokens", settings.max_context_tokens),
                        keep=("messages", 20),
                    ),
                ],
                checkpointer=saver,
            ),
        )
    return _AGENT[1]

