"""Read-only LangChain tools the LLM can call during an investigation, grouped
by backend: docker, prometheus, loki."""

from agent.tools.docker import docker_logs, docker_status, list_services
from agent.tools.loki import get_loki_label_values, query_loki, query_loki_range
from agent.tools.prometheus import (
    get_label_values,
    list_metric_names,
    query_prometheus,
    query_prometheus_range,
)

ALL_TOOLS = [
    list_services,
    docker_status,
    docker_logs,
    query_prometheus,
    list_metric_names,
    get_label_values,
    query_prometheus_range,
    get_loki_label_values,
    query_loki,
    query_loki_range,
]

__all__ = [
    "ALL_TOOLS",
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
