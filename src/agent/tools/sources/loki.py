"""Grafana Loki query helper."""

from datetime import datetime, timedelta, timezone

import httpx2 as httpx

from agent.config.settings import settings


def _loki_headers() -> dict[str, str]:
    if settings.loki_token:
        return {"Authorization": f"Bearer {settings.loki_token}"}
    return {}


async def query_loki(query: str, limit: int = 100) -> dict:
    """Run a LogQL query against Loki, scoped to a short recent window.

    Loki's instant ``/query`` endpoint only accepts metric-type LogQL (``rate()``,
    ``count_over_time()``) — a plain log-stream selector, which is this tool's
    entire purpose, gets rejected outright: "log queries are not supported as
    an instant query type, please change your query to a range query type."
    Delegates to ``query_loki_range`` under a short default window instead of
    hitting the broken endpoint.
    """
    return await query_loki_range(query, minutes=15, limit=limit)


async def query_loki_range(query: str, minutes: int, limit: int = 100) -> dict:
    """Run a LogQL range query over the last `minutes`."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=minutes)
    url = f"{settings.loki_url}/loki/api/v1/query_range"
    headers = _loki_headers()
    params = {
        "query": query,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "limit": limit,
    }
    async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()
