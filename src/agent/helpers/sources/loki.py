"""Grafana Loki query helper."""

import re
from datetime import datetime, timedelta, timezone

import httpx2 as httpx

from agent.config.settings import settings

_LABEL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _loki_headers() -> dict[str, str]:
    if settings.loki_token:
        return {"Authorization": f"Bearer {settings.loki_token}"}
    return {}


async def get_label_values(label: str) -> list[str]:
    """List values for a given Loki stream label.

    Loki's label schema is set by Promtail's scrape config, not by Docker
    container names — it commonly has no 'container' label at all (this stack's
    labels are 'job', 'service', 'service_name', 'filename'). Callers must not
    assume Prometheus's label set applies here; discover it instead.
    """
    if not _LABEL_RE.match(label):
        return []
    url = f"{settings.loki_url}/loki/api/v1/label/{label}/values"
    headers = _loki_headers()
    async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json().get("data", []) or []


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
