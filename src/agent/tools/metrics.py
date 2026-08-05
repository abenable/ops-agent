"""Metrics retrieval tools."""

from agent.tools.normalize import regex_parts
from agent.tools.sources import prometheus


def _escape_label_value(value: str) -> str:
    """Escape quotes and backslashes for a PromQL label matcher value."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


async def get_service_metrics(service: str) -> dict:
    """Return metrics for a service from Prometheus, with a fallback message."""
    try:
        frag = _escape_label_value(regex_parts(service))
        result = await prometheus.query_prometheus(
            f'avg(process_cpu_seconds_total{{service=~".*{frag}.*"}})'
        )
        if not result.get("data", {}).get("result"):
            return {
                "service": service,
                "message": f"No Prometheus metrics found for '{service}' — it may not expose a /metrics endpoint.",
            }
        return result
    except Exception:
        return {
            "service": service,
            "message": "Prometheus unreachable.",
        }
