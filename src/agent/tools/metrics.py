"""Metrics retrieval tools."""


async def get_service_metrics(service: str) -> dict:
    """Return metrics for a service.

    Replace this stub with Prometheus or another metrics source.
    """
    return {"service": service, "cpu_percent": 0.0, "memory_percent": 0.0}
