"""Discord-specific helpers."""

from pathlib import Path

import discord

from agent.config.settings import settings
from agent.tasks import task_path  # operator-facing alias; the on-disk unit is a task
from agent.tools import docker


def build_info_embed(bot_user: discord.ClientUser | None) -> discord.Embed:
    """Build the standard info embed used by /info."""
    display_name = bot_user.display_name if bot_user else "Oracle"
    embed = discord.Embed(
        title=f"{display_name} — Infrastructure Ops Agent",
        color=0x3498DB,
    )
    embed.add_field(name="Library", value=f"discord.py {discord.__version__}", inline=False)
    embed.add_field(name="Commands", value="`/` slash commands", inline=False)
    if settings.bot_creators:
        embed.add_field(name="Creators", value=settings.bot_creators, inline=False)
    if settings.bot_support_server:
        embed.add_field(name="Support Server", value=settings.bot_support_server, inline=False)
    if settings.bot_website:
        embed.add_field(name="Website", value=settings.bot_website, inline=False)
    contact = settings.bot_contact or "Not configured"
    embed.add_field(name="Questions / Concerns", value=contact, inline=False)
    return embed


def format_container_list(items: list[dict]) -> str:
    """Render container list grouped by state (running, exited, etc.)."""
    groups: dict[str, list[dict]] = {}
    for c in items:
        state = (c.get("State") or "unknown").lower()
        groups.setdefault(state, []).append(c)

    # Show running first; keep the rest alphabetical.
    order = sorted(groups.keys(), key=lambda s: (0 if s == "running" else 1, s))

    lines: list[str] = []
    for state in order:
        containers = groups[state]
        lines.append(f"**{state.capitalize()}** ({len(containers)})")
        for c in containers:
            lines.append(f"- `{docker.container_name(c)}` — {c.get('Status', '')}")
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


def format_prometheus(result: dict) -> str:
    """Render a Prometheus query response as human-readable lines, not JSON."""
    data = result.get("data", {})
    if data.get("resultType") == "scalar":
        return str(data.get("result", ["", "?"])[1])

    series = data.get("result") or []
    if not series:
        return "No data."

    lines = []
    for s in series:
        metric = s.get("metric", {})
        name = metric.get("service") or metric.get("instance") or metric.get("__name__") or "value"
        value = s.get("value", [None, "?"])[1]
        lines.append(f"{name}: {value}")
    return "\n".join(lines)


def format_status(result: dict) -> str:
    """Render a get_service_status() dict as a one-line human summary."""
    if result["status"] == "not found":
        return f"No container matching '{result['service']}'."
    dot = "🟢" if result["status"] == "running" else "🔴"
    return (
        f"{dot} {result['container']} — {result['status']} "
        f"({result['detail']}) · {result['image']}"
    )


def format_loki(result: dict, limit: int = 25) -> str:
    """Render a Loki query response as plain log lines, not JSON."""
    streams = result.get("data", {}).get("result", [])
    lines = [line for s in streams for _ts, line in s.get("values", [])]
    if not lines:
        return "No logs."
    return "\n".join(lines[-limit:])
