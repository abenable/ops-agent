"""Log retrieval tools."""

from agent.bot.utils import format_loki
from agent.tools.normalize import regex_parts
from agent.tools.sources import loki


async def get_recent_logs(service: str, lines: int = 10) -> str:
    """Return recent logs for a service, fetching from Loki if reachable.

    Tries the ``service``, ``container``, and ``name`` labels in turn with a
    separator-agnostic regex, so a user spelling of ``agent_api`` still matches
    the real stream label ``marconi-agent-api``.
    """
    frag = regex_parts(service)
    selectors = [
        f'{{service=~".*{frag}.*"}}',
        f'{{container=~".*{frag}.*"}}',
        f'{{name=~".*{frag}.*"}}',
    ]
    result: dict = {}
    for sel in selectors:
        try:
            result = await loki.query_loki(sel, limit=lines)
        except Exception:
            return f"// ponytail: stub log output for {service} ({lines} lines)"
        if result.get("data", {}).get("result"):
            return format_loki(result, limit=lines)
    return format_loki(result, limit=lines)
