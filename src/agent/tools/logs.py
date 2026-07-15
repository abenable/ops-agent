"""Log retrieval tools."""

from agent.tools.sources import loki


async def get_recent_logs(service: str, lines: int = 10) -> str:
    """Return recent logs for a service, fetching from Loki if reachable."""
    try:
        result = await loki.query_loki(f'{{service="{service}"}}', limit=lines)
        return str(result.get("data", result))
    except Exception:
        return f"// ponytail: stub log output for {service} ({lines} lines)"
