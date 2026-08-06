"""Send raw tool outputs through the LLM for a cleaned, human-readable summary."""

import re

from agent.llm.client import get_llm

# How much raw output we feed to the LLM for context.
_MAX_RAW_LEN = 3500
# How much raw output we show in the fallback code block (keeps the whole
# message inside Discord's 2000-char limit with room for the prefix line).
_MAX_DISPLAY = 1800
# Hard cap on anything we return, so a caller can always send it in one message.
_MAX_OUT_LEN = 1900

# Markdown ATX headings (## Foo) — Discord renders these as literal text, so
# normalize them to **bold**. Small models emit `####` even when asked not to.
_HEADING_RE = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)


def _sanitize(value: str) -> str:
    """Collapse whitespace and cap length so user input cannot inject prompt lines."""
    return " ".join(str(value).split())[:200]


def _discordify(text: str) -> str:
    """Normalize markdown heading syntax to Discord **bold**.

    Discord does not render ``#``/``##``/``####`` headings — they show as literal
    text. Small models emit them despite prompt instructions, so we convert
    ``## Foo`` to ``**Foo**``. Content inside ``` code fences is left untouched
    so a ``# comment`` inside a pasted log block is not mangled.
    """
    parts = text.split("```")
    for i in range(0, len(parts), 2):  # even indices are outside code fences
        parts[i] = _HEADING_RE.sub(r"**\1**", parts[i])
    return "```".join(parts)


def _fit(text: str) -> str:
    """Cap a string so it always fits in a single Discord message."""
    if len(text) <= _MAX_OUT_LEN:
        return text
    return text[: _MAX_OUT_LEN - 1].rstrip() + "\u2026"


async def clean(raw: str, *, service: str, action: str) -> str:
    """Ask the configured LLM to turn raw tool output into a concise summary.

    Falls back to the (truncated) raw output if the LLM is unreachable or returns
    an empty answer, so commands never fail silently.
    """
    if not raw.strip():
        return "Nothing to show."

    svc = _sanitize(service)
    prompt = (
        f"You are Oracle, a terse infrastructure-operations assistant.\n"
        f"The user asked you to {action} for `{svc}`.\n"
        f"Summarize the raw output below using Discord markdown formatting:\n"
        f"- Use **bold** for each section header (e.g. **Build Workflow Index**).\n"
        f"- Do NOT use `#`/`##`/`####` heading syntax — Discord renders it as literal text.\n"
        f"- Use bullet lists (`-`) for items.\n"
        f"- Wrap container names, IDs, and URLs in backticks.\n"
        f"- Keep each paragraph short and scannable; avoid one huge wall of text.\n"
        f"- Put multi-line raw data inside ``` code blocks only if needed.\n"
        f"Highlight any problems, anomalies, or important numbers.\n\n"
        f"Raw output:\n```\n{raw[:_MAX_RAW_LEN]}\n```"
    )

    try:
        result = (await get_llm(temperature=0.0).ainvoke(prompt)).content.strip()
    except Exception as exc:
        return _fit(
            f"*LLM clean unavailable ({exc}); showing raw output:*\n"
            f"```\n{raw[:_MAX_DISPLAY]}\n```"
        )

    if not result:
        # LLM returned nothing usable; show the raw output instead of an empty message.
        return _fit(f"```\n{raw[:_MAX_DISPLAY]}\n```")
    return _fit(_discordify(result))
