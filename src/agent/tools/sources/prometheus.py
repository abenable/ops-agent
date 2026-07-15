"""Prometheus / VictoriaMetrics query helper."""

import httpx2 as httpx

from agent.config.settings import settings


async def query_prometheus(query: str) -> dict:
    """Run a PromQL query against a Prometheus-compatible endpoint."""
    url = f"{settings.prometheus_url}/api/v1/query"
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params={"query": query})
        response.raise_for_status()
        return response.json()
