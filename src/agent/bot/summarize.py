"""Send raw tool outputs through the LLM for a cleaned, human-readable summary."""

from agent.llm.client import get_llm

_MAX_RAW_LEN = 3500


async def clean(raw: str, *, service: str, action: str) -> str:
    """Ask the configured LLM to turn raw tool output into a concise summary.

    Falls back to the raw output (truncated) if the LLM is unreachable, so commands
    never fail silently.
    """
    if not raw.strip():
        return "Nothing to show."

    prompt = (
        f"You are Oracle, a terse infrastructure-operations assistant.\n"
        f"The user asked you to {action} for `{service}`.\n"
        f"Summarize the raw output below using Discord markdown formatting:\n"
        f"- Use **bold** section headers for each group or category.\n"
        f"- Use bullet lists (`-`) for items.\n"
        f"- Wrap container names, IDs, and URLs in backticks.\n"
        f"- Keep each paragraph short and scannable; avoid one huge wall of text.\n"
        f"- Put multi-line raw data inside ``` code blocks only if needed.\n"
        f"Highlight any problems, anomalies, or important numbers.\n\n"
        f"Raw output:\n```\n{raw[:_MAX_RAW_LEN]}\n```"
    )

    try:
        return (await get_llm(temperature=0.0).ainvoke(prompt)).content.strip()
    except Exception as exc:
        return (
            f"*LLM clean unavailable ({exc}); showing raw output:*\n"
            f"```\n{raw[:2000]}\n```"
        )
