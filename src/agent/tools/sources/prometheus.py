"""Prometheus / VictoriaMetrics query helper."""

import httpx2 as httpx

from agent.config.settings import settings


def _prometheus_headers() -> dict[str, str]:
    if settings.prometheus_token:
        return {"Authorization": f"Bearer {settings.prometheus_token}"}
    return {}


async def query_prometheus(query: str) -> dict:
    """Run a PromQL query against a Prometheus-compatible endpoint."""
    url = f"{settings.prometheus_url}/api/v1/query"
    headers = _prometheus_headers()
    async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
        response = await client.get(url, params={"query": query})
        response.raise_for_status()
        return response.json()
