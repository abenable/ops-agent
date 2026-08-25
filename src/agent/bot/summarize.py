"""Send raw tool outputs through the LLM for a cleaned, human-readable summary."""

import re

from langchain.chat_models import init_chat_model
from langchain_core.prompts import ChatPromptTemplate

from agent.config.settings import settings

_MAX_RAW_LEN = 3500
_MAX_DISPLAY = 1800
_MAX_OUT_LEN = 1900

_HEADING_RE = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)

_ROW_RE = re.compile(r"^\|.*\|\s*$")
_SEP_RE = re.compile(r"^\|[\s:|-]+\|\s*$")


def _sanitize(value: str) -> str:
    """Collapse whitespace and cap length so user input cannot inject prompt lines."""
    return " ".join(str(value).split())[:200]


def _split_row(line: str) -> list[str]:
    s = line.strip()
    s = s.removeprefix("|")
    s = s.removesuffix("|")
    return [c.strip() for c in s.split("|")]


def _convert_tables(text: str) -> str:
    """Turn a markdown table into Discord bullets."""
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        if i + 1 < len(lines) and _ROW_RE.match(lines[i].strip()) and _SEP_RE.match(lines[i + 1].strip()):
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and _ROW_RE.match(lines[i].strip()):
                rows.append(_split_row(lines[i]))
                i += 1
            for row in rows:
                if not row:
                    continue
                label = row[0]
                rest = row[1:]
                if len(rest) <= 1:
                    out.append(f"- **{label}:** {rest[0] if rest else ''}".rstrip())
                else:
                    out.append(f"- **{label}:** " + " \u00b7 ".join(rest))
            out.append("")
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


def discordify(text: str) -> str:
    """Normalize markdown Discord can't render: ``#`` headings -> **bold** and markdown tables -> bullet lists."""
    parts = text.split("```")
    for i in range(0, len(parts), 2):
        parts[i] = _HEADING_RE.sub(r"**\1**", parts[i])
        parts[i] = _convert_tables(parts[i])
    return "```".join(parts)


_CLEAN_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", "You are Oracle, a terse infrastructure-operations assistant."),
        (
            "user",
            (
                "The user asked you to {action} for `{service}`.\n"
                "Summarize the raw output below using Discord markdown formatting:\n"
                "- Use **bold** for each section header (e.g. **Build Workflow Index**).\n"
                "- Do NOT use `#`/`##`/`####` heading syntax — Discord renders it as literal text.\n"
                "- Use bullet lists (`-`) for items.\n"
                "- Wrap container names, IDs, and URLs in backticks.\n"
                "- Keep each paragraph short and scannable; avoid one huge wall of text.\n"
                "- Put multi-line raw data inside ``` code blocks only if needed.\n"
                "Highlight any problems, anomalies, or important numbers.\n\n"
                "Raw output:\n```\n{raw}\n```"
            ),
        ),
    ]
)


def _fit(text: str) -> str:
    """Cap a string so it always fits in a single Discord message."""
    if len(text) <= _MAX_OUT_LEN:
        return text
    return text[: _MAX_OUT_LEN - 1].rstrip() + "\u2026"


async def clean(raw: str, *, service: str, action: str) -> str:
    """Ask the configured LLM to turn raw tool output into a concise summary."""
    if not raw.strip():
        return "Nothing to show."

    svc = _sanitize(service)
    messages = _CLEAN_PROMPT.invoke(
        {"service": svc, "action": action, "raw": raw[:_MAX_RAW_LEN]}
    ).to_messages()

    try:
        result = (await init_chat_model(settings.model_id).ainvoke(messages)).content.strip()
    except Exception as exc:  # noqa: BLE001
        return _fit(
            f"*LLM clean unavailable ({exc}); showing raw output:*\n"
            f"```\n{raw[:_MAX_DISPLAY]}\n```"
        )

    if not result:
        return _fit(f"```\n{raw[:_MAX_DISPLAY]}\n```")
    return _fit(discordify(result))
