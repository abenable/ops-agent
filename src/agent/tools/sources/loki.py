"""Grafana Loki query helper."""

import httpx2 as httpx

from agent.config.settings import settings


async def query_loki(query: str, limit: int = 100) -> dict:
    """Run a LogQL query against a Loki endpoint."""
    url = f"{settings.loki_url}/loki/api/v1/query"
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params={"query": query, "limit": limit})
        response.raise_for_status()
        return response.json()
