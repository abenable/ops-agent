"""Metrics retrieval tools."""

from agent.tools import docker
from agent.tools.sources import prometheus


def _escape_label_value(value: str) -> str:
    """Escape quotes and backslashes for a PromQL label matcher value."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


async def get_service_metrics(service: str) -> dict:
    """Return every current metric Prometheus has for a service's scrape job,
    with a fallback message when it isn't scraped or Prometheus is down.

    Two things must be right for this to find anything: the label (Prometheus
    scrape jobs here are keyed on 'job', not 'service' — no series ever
    carries a 'service' label) and the metric name. There is no metric name
    safe to hardcode across jobs: different targets expose different families
    under different (sometimes prefixed — n8n's prom-client metrics are named
    'n8n_process_...', not 'process_...') names, and most jobs in this stack
    don't expose a standard 'process_cpu_seconds_total' series at all. So this
    queries the bare job selector and returns whatever series exist, the same
    way an investigator would discover them with list_metric_names /
    get_label_values instead of guessing one name up front.
    """
    try:
        job = _escape_label_value(await docker.resolve_label_name(service))
        result = await prometheus.query_prometheus(f'{{job="{job}"}}')
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
