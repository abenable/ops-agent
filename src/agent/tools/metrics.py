"""Metrics retrieval tools."""

from agent.tools.sources import prometheus


async def get_service_metrics(service: str) -> dict:
    """Return metrics for a service, fetching from Prometheus if reachable."""
    try:
        return await prometheus.query_prometheus(
            f'avg(process_cpu_seconds_total{{service=~".*{service}.*"}})'
        )
    except Exception:
        return {"service": service, "cpu_percent": 0.0, "memory_percent": 0.0}
