"""Read-only LangChain tools the LLM can call during an investigation."""

from langchain_core.tools import tool

from agent.config.settings import settings
from agent.tools.sources import loki, prometheus


@tool
async def query_prometheus(promql: str) -> str:
    """Run an instant PromQL query. Use for current values, e.g. 'up == 0' or
    'rate(http_requests_total[5m])'. Returns the JSON result as a string."""
    return str(await prometheus.query_prometheus(promql))[:4000]


@tool
async def list_metric_names(match: str = "") -> str:
    """List available Prometheus metric names. Call this FIRST to discover what
    metrics exist before writing a query. `match` optionally filters by substring."""
    names = await prometheus.list_metric_names(match)
    return "\n".join(names[:250]) if names else "(no metrics found)"


@tool
async def get_label_values(label: str) -> str:
    """List values for a Prometheus label such as 'service', 'job', or 'instance'.
    Use this to discover valid label values before querying."""
    values = await prometheus.get_label_values(label)
    return "\n".join(values[:250]) if values else f"(no values for label {label})"


@tool
async def query_prometheus_range(promql: str, minutes: int) -> str:
    """Run a PromQL range query over the last `minutes`. Use for trends
    (e.g. CPU over the last 30m). The window is clamped to the configured maximum."""
    max_minutes = max(1, settings.range_max_hours * 60)
    minutes = max(1, min(minutes, max_minutes))
    return str(await prometheus.query_prometheus_range(promql, minutes))[:4000]


@tool
async def query_loki(logql: str, limit: int = 100) -> str:
    """Run a LogQL query against Loki. Use this to pull logs the query scopes itself.
    Keep `limit` small; it is clamped to the configured maximum."""
    limit = max(1, min(limit, settings.loki_max_limit))
    return str(await loki.query_loki(logql, limit))[:4000]
