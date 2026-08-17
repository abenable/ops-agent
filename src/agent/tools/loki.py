"""Read-only Loki client (REST API over httpx2) + LangChain tools."""

import re
from datetime import UTC, datetime, timedelta

import httpx2 as httpx
from langchain_core.tools import tool

from agent.config.settings import settings

_LABEL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


def _headers() -> dict[str, str]:
    if settings.loki_token:
        return {"Authorization": f"Bearer {settings.loki_token}"}
    return {}


async def label_values(label: str) -> list[str]:
    """List values for a given Loki stream label.

    Loki's label schema is set by Promtail's scrape config, not by Docker
    container names — it commonly has no 'container' label at all. Callers
    must discover the real labels instead of assuming Prometheus's set.
    """
    if not _LABEL_RE.match(label):
        return []
    url = f"{settings.loki_url}/loki/api/v1/label/{label}/values"
    async with httpx.AsyncClient(timeout=10.0, headers=_headers()) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json().get("data", []) or []


async def query_range(logql: str, minutes: int, limit: int = 100) -> dict:
    """Run a LogQL range query over the last `minutes`."""
    end = datetime.now(UTC)
    start = end - timedelta(minutes=minutes)
    url = f"{settings.loki_url}/loki/api/v1/query_range"
    params = {
        "query": logql,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "limit": limit,
    }
    async with httpx.AsyncClient(timeout=10.0, headers=_headers()) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()


async def query(logql: str, limit: int = 100) -> dict:
    """Run a LogQL query scoped to a short recent window.

    Loki's instant ``/query`` endpoint rejects plain log-stream selectors
    ("log queries are not supported as an instant query type"), so this
    delegates to a short range query instead.
    """
    return await query_range(logql, minutes=15, limit=limit)


# ---------------------------------------------------------------------------
# LangChain tools
# ---------------------------------------------------------------------------


@tool
async def get_loki_label_values(label: str) -> str:
    """List values for a Loki stream label such as 'service' or 'job'. Loki's
    label schema is set by Promtail and is NOT the same as Prometheus's or a
    Docker container name — do not guess a label like 'container'; call this
    first to learn the real label values before writing a LogQL selector."""
    values = await label_values(label)
    return "\n".join(values[:250]) if values else f"(no values for label {label})"


@tool
async def query_loki(logql: str, limit: int = 100) -> str:
    """Run an instant LogQL query against Loki. Use this to pull logs the query scopes itself.
    Keep `limit` small; it is clamped to the configured maximum."""
    limit = max(1, min(limit, settings.loki_max_limit))
    return str(await query(logql, limit))[:4000]


@tool
async def query_loki_range(logql: str, minutes: int, limit: int = 100) -> str:
    """Run a LogQL range query over the last `minutes`. Prefer this when the user
    asks for logs over a recent window. The window and limit are clamped."""
    limit = max(1, min(limit, settings.loki_max_limit))
    minutes = max(1, min(minutes, settings.range_max_hours * 60))
    return str(await query_range(logql, minutes, limit))[:4000]
