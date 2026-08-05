"""Prometheus / VictoriaMetrics query helper."""

import re
from datetime import datetime, timedelta, timezone

import httpx2 as httpx

from agent.config.settings import settings

# Prometheus label names: [a-zA-Z_][a-zA-Z0-9_]*. We allow the common charset and
# reject anything that could manipulate the URL path (/, ?, #, .., whitespace).
_LABEL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _prometheus_headers() -> dict[str, str]:
    if settings.prometheus_token:
        return {"Authorization": f"Bearer {settings.prometheus_token}"}
    return {}


async def query_prometheus(query: str) -> dict:
    """Run a PromQL instant query against a Prometheus-compatible endpoint."""
    url = f"{settings.prometheus_url}/api/v1/query"
    headers = _prometheus_headers()
    async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
        response = await client.get(url, params={"query": query})
        response.raise_for_status()
        return response.json()


async def list_metric_names(match: str = "") -> list[str]:
    """List available Prometheus metric names, optionally filtered by substring."""
    url = f"{settings.prometheus_url}/api/v1/label/__name__/values"
    headers = _prometheus_headers()
    async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
        response = await client.get(url)
        response.raise_for_status()
        names = response.json().get("data", []) or []

    if match:
        match_lower = match.lower()
        names = [n for n in names if match_lower in n.lower()]
    return names[:500]


async def get_label_values(label: str) -> list[str]:
    """List values for a given Prometheus label."""
    if not _LABEL_RE.match(label):
        return []
    url = f"{settings.prometheus_url}/api/v1/label/{label}/values"
    headers = _prometheus_headers()
    async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json().get("data", []) or []


async def query_prometheus_range(promql: str, minutes: int) -> dict:
    """Run a PromQL range query over the last `minutes`."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=minutes)
    step_seconds = max(15, minutes * 60 // 100)
    url = f"{settings.prometheus_url}/api/v1/query_range"
    headers = _prometheus_headers()
    params = {
        "query": promql,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "step": f"{step_seconds}s",
    }
    async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()
