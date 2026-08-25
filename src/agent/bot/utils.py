"""Discord-specific helpers."""

from agent.tools.docker import container_name


def format_container_list(items: list[dict]) -> str:
    """Render container list grouped by state (running, exited, etc.)."""
    groups: dict[str, list[dict]] = {}
    for c in items:
        state = (c.get("State") or "unknown").lower()
        groups.setdefault(state, []).append(c)

    order = sorted(groups.keys(), key=lambda s: (0 if s == "running" else 1, s))

    lines: list[str] = []
    for state in order:
        containers = groups[state]
        lines.append(f"**{state.capitalize()}** ({len(containers)})")
        for c in containers:
            lines.append(f"- `{container_name(c)}` — {c.get('Status', '')}")
        lines.append("")
    return "\n".join(lines).strip()


def split_discord_text(text: str, max_len: int = 1900) -> list[str]:
    """Split a long message into chunks that fit Discord's 2000-character limit."""
    if not text:
        return []

    chunks: list[str] = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break

        split_at = text.rfind("\n", 0, max_len)
        if split_at <= 0:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    return chunks
