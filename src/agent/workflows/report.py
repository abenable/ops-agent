"""Structured incident report: the same investigation loop, fixed prompt."""

from langchain_core.prompts import ChatPromptTemplate

from agent.workflows.investigate import investigate

_REPORT_TEMPLATE = ChatPromptTemplate.from_template(
    """Write a structured incident report for the service `{service}`.

Use the tools to check its container state, recent logs, and metrics before
writing anything. Then answer with exactly these sections:

**Summary** — one or two sentences.
**What happened** — observed behavior and timeline.
**Evidence** — the log lines / metric values that back it up.
**Likely cause** — your best-supported hypothesis.
**Recommended next steps** — actions for a human operator (you are read-only).

If the service looks healthy, say so plainly in the Summary and keep the rest short."""
)


async def report(service: str) -> str:
    """Generate a structured incident report for one service (always one-shot)."""
    question = _REPORT_TEMPLATE.format_messages(service=service)[0].content
    return await investigate(question)
