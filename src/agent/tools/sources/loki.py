"""Grafana Loki query helper."""

from datetime import datetime, timedelta, timezone

import httpx2 as httpx

from agent.config.settings import settings


def _loki_headers() -> dict[str, str]:
    if settings.loki_token:
        return {"Authorization": f"Bearer {settings.loki_token}"}
    return {}


async def query_loki(query: str, limit: int = 100) -> dict:
    """Run an instant LogQL query against a Loki endpoint."""
    url = f"{settings.loki_url}/loki/api/v1/query"
    headers = _loki_headers()
    async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
        response = await client.get(url, params={"query": query, "limit": limit})
        response.raise_for_status()
        return response.json()


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
