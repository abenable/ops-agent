"""Grafana Loki query helper."""

import httpx2 as httpx

from agent.config.settings import settings


def _loki_headers() -> dict[str, str]:
    if settings.loki_token:
        return {"Authorization": f"Bearer {settings.loki_token}"}
    return {}


async def query_loki(query: str, limit: int = 100) -> dict:
    """Run a LogQL query against a Loki endpoint."""
    url = f"{settings.loki_url}/loki/api/v1/query"
    headers = _loki_headers()
    async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
        response = await client.get(url, params={"query": query, "limit": limit})
        response.raise_for_status()
        return response.json()
