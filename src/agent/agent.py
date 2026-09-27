"""Builds and caches the Oracle agent shared by every workflow."""

from langchain.agents import create_agent
from langchain.agents.middleware import (
    HumanInTheLoopMiddleware,
    ModelRetryMiddleware,
    SummarizationMiddleware,
    ToolCallLimitMiddleware,
    ToolErrorMiddleware,
    ToolRetryMiddleware,
)
from langchain.chat_models import init_chat_model

from agent.config.settings import settings
from agent.memory import checkpointer
from agent.tools import ALL_TOOLS, configured_tools

_LLM_TIMEOUT = 30.0

_TOOLS_BY_NAME = {t.name: t for t in ALL_TOOLS}

_SYSTEM_PROMPT = """
You are Oracle, a terse, read-only infrastructure-operations assistant for the Marconi lab. 
Your sole purpose is to investigate and answer questions about the lab's Docker services. 
If a user asks about topics outside of Marconi lab infrastructure, briefly decline to answer.

[TOOL CONSTRAINTS]
- ONLY call tools explicitly provided to you in this conversation. That list is authoritative; no other tool exists under any name.
- NEVER guess a tool name, invent a variation of one, or assume an unlisted capability.
- If a tool call fails with "not a valid tool", accept it as final: do not retry name variations.
- A missing capability is a complete answer, not a failure: if no provided tool can check something, say so plainly and answer from the evidence you have.

[INVESTIGATION WORKFLOW]
1. Discover: If unsure of an exact service name and a service-discovery tool is provided, call it first.
2. Verify: Prefer evidence over guessing, but only through the tools explicitly provided. If the provided tools cannot fully answer the question, answer from the evidence you have and say what you could not verify.
3. Read-Only: You cannot mutate state. Never claim you can restart, modify, or fix services.

[OUTPUT FORMATTING]
- Tone: Be extremely concise and objective. This is a quick chat channel, not a detailed report.
- Allowed Markdown: Use **bold** for section headers, standard bullet lists, and `backticks` for container names, metrics, and values.
- Banned Markdown: Do NOT use `#` headings or Markdown tables.
- Conclusion: End every investigation with exactly two brief sections: **Likely Cause** and **Recommended Action** (directing a human operator on what to do).
"""

_AGENT: tuple | None = None


async def _tool_error(exc: Exception, request) -> str:
    """Return a tool failure to the model as a ToolMessage so it can react."""
    return f"(tool '{request.tool_call['name']}' failed: {exc})"


def _build_agent(saver, tools: list, approval: bool = False):
    # Approval pauses the run before any tool executes until a person approves or rejects each call.
    approve = (
        [HumanInTheLoopMiddleware({t.name: {"allowed_decisions": ["approve", "reject"]} for t in tools})]
        if approval
        else []
    )
    return create_agent(
        model=init_chat_model(settings.model_id, timeout=_LLM_TIMEOUT),
        tools=tools,
        system_prompt=_SYSTEM_PROMPT,
        middleware=[
            *approve,
            ModelRetryMiddleware(max_retries=2),
            ToolCallLimitMiddleware(
                run_limit=settings.max_tool_steps,
                exit_behavior="end",
            ),
            ToolRetryMiddleware(max_retries=1),
            ToolErrorMiddleware(aon_error=_tool_error),
            SummarizationMiddleware(
                model=init_chat_model(settings.summarizer_model_id, timeout=_LLM_TIMEOUT),
                trigger=("tokens", settings.max_context_tokens),
                keep=("messages", 20),
            ),
        ],
        checkpointer=saver,
    )


async def get_agent(tools: list | None = None, approval: bool = False):
    """The Oracle agent: real system prompt, middleware, model, and checkpointer.

    ``tools`` narrows it to those tools (names or tool objects); ``approval`` makes every
    tool call wait for a person's decision. Either builds a fresh agent; the default is cached.
    """
    global _AGENT
    saver = await checkpointer()
    if tools is not None or approval:
        resolved = [
            _TOOLS_BY_NAME.get(t, t) if isinstance(t, str) else _TOOLS_BY_NAME.get(t.name, t)
            for t in (tools if tools is not None else configured_tools())
        ]
        return _build_agent(saver, resolved, approval)
    if _AGENT is None or _AGENT[0] is not saver:
        _AGENT = (saver, _build_agent(saver, [_TOOLS_BY_NAME[t.name] for t in configured_tools()]))
    return _AGENT[1]
