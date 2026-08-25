"""Read-only LangChain tools the LLM can call during an investigation, grouped by backend: docker, prometheus, loki."""

from agent.config.settings import settings
from agent.tools.docker import docker_logs, docker_status, list_services
from agent.tools.loki import get_loki_label_values, query_loki, query_loki_range
from agent.tools.prometheus import (
    get_label_values,
    list_metric_names,
    query_prometheus,
    query_prometheus_range,
)

DOCKER_TOOLS = [list_services, docker_status, docker_logs]
PROMETHEUS_TOOLS = [query_prometheus, list_metric_names, get_label_values, query_prometheus_range]
LOKI_TOOLS = [get_loki_label_values, query_loki, query_loki_range]

ALL_TOOLS = [*DOCKER_TOOLS, *PROMETHEUS_TOOLS, *LOKI_TOOLS]


def configured_tools() -> list:
    """``ALL_TOOLS`` minus any backend without a URL.

    A tool that cannot work is worse than an absent one: called, it fails, and
    the model reads that failure as "the backend is down" rather than "it was
    never configured" — which is a wrong diagnosis, not a missing one.
    """
    return [
        *DOCKER_TOOLS,
        *(PROMETHEUS_TOOLS if settings.prometheus_url else []),
        *(LOKI_TOOLS if settings.loki_url else []),
    ]

__all__ = [
    "ALL_TOOLS",
    "DOCKER_TOOLS",
    "LOKI_TOOLS",
    "PROMETHEUS_TOOLS",
    "configured_tools",
    "docker_logs",
    "docker_status",
    "get_label_values",
    "get_loki_label_values",
    "list_metric_names",
    "list_services",
    "query_loki",
    "query_loki_range",
    "query_prometheus",
    "query_prometheus_range",
]
