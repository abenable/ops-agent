"""Metrics retrieval tools."""

from agent.tools.sources import prometheus


def _escape_label_value(value: str) -> str:
    """Escape quotes and backslashes for a PromQL label matcher value."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


async def get_service_metrics(service: str) -> dict:
    """Return metrics for a service, fetching from Prometheus if reachable."""
    try:
        escaped = _escape_label_value(service)
        return await prometheus.query_prometheus(
            f'avg(process_cpu_seconds_total{{service=~".*{escaped}.*"}})'
        )
    except Exception:
        return {"service": service, "cpu_percent": 0.0, "memory_percent": 0.0}
