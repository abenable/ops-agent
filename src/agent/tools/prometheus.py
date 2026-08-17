"""Read-only Prometheus client (REST API over httpx2) + LangChain tools."""

import re
from datetime import UTC, datetime, timedelta

import httpx2 as httpx
from langchain_core.tools import tool

from agent.config.settings import settings

# Prometheus label names: [a-zA-Z_][a-zA-Z0-9_]*. Reject anything that could
# manipulate the URL path (/, ?, #, .., whitespace).
_LABEL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


def _headers() -> dict[str, str]:
    if settings.prometheus_token:
        return {"Authorization": f"Bearer {settings.prometheus_token}"}
    return {}


async def query(promql: str) -> dict:
    """Run a PromQL instant query against a Prometheus-compatible endpoint."""
    url = f"{settings.prometheus_url}/api/v1/query"
    async with httpx.AsyncClient(timeout=10.0, headers=_headers()) as client:
        response = await client.get(url, params={"query": promql})
        response.raise_for_status()
        return response.json()


async def metric_names(match: str = "") -> list[str]:
    """List available metric names, optionally filtered by substring."""
    url = f"{settings.prometheus_url}/api/v1/label/__name__/values"
    async with httpx.AsyncClient(timeout=10.0, headers=_headers()) as client:
        response = await client.get(url)
        response.raise_for_status()
        names = response.json().get("data", []) or []
    if match:
        needle = match.lower()
        names = [n for n in names if needle in n.lower()]
    return names[:500]


async def label_values(label: str) -> list[str]:
    """List values for a given Prometheus label."""
    if not _LABEL_RE.match(label):
        return []
    url = f"{settings.prometheus_url}/api/v1/label/{label}/values"
    async with httpx.AsyncClient(timeout=10.0, headers=_headers()) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json().get("data", []) or []


async def query_range(promql: str, minutes: int) -> dict:
    """Run a PromQL range query over the last `minutes`."""
    end = datetime.now(UTC)
    start = end - timedelta(minutes=minutes)
    step_seconds = max(15, minutes * 60 // 100)
    url = f"{settings.prometheus_url}/api/v1/query_range"
    params = {
        "query": promql,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "step": f"{step_seconds}s",
    }
    async with httpx.AsyncClient(timeout=10.0, headers=_headers()) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()


# ---------------------------------------------------------------------------
# LangChain tools
# ---------------------------------------------------------------------------


@tool
async def query_prometheus(promql: str) -> str:
    """Run an instant PromQL query. Use for current values, e.g. 'up == 0' or
    'rate(http_requests_total[5m])'. Returns the JSON result as a string."""
    return str(await query(promql))[:4000]


@tool
async def list_metric_names(match: str = "") -> str:
    """List available Prometheus metric names. Call this FIRST to discover what
    metrics exist before writing a query. `match` optionally filters by substring."""
    names = await metric_names(match)
    return "\n".join(names[:250]) if names else "(no metrics found)"


@tool
async def get_label_values(label: str) -> str:
    """List values for a Prometheus label such as 'service', 'job', or 'instance'.
    Use this to discover valid label values before querying."""
    values = await label_values(label)
    return "\n".join(values[:250]) if values else f"(no values for label {label})"


@tool
async def query_prometheus_range(promql: str, minutes: int) -> str:
    """Run a PromQL range query over the last `minutes`. Use for trends
    (e.g. CPU over the last 30m). The window is clamped to the configured maximum."""
    max_minutes = max(1, settings.range_max_hours * 60)
    minutes = max(1, min(minutes, max_minutes))
    return str(await query_range(promql, minutes))[:4000]
