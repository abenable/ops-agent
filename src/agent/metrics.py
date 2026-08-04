"""Prometheus metrics for the ops-agent itself.

Registers counters and histograms for the agentic investigation loop,
API requests, monitor cycles, and alert events.  A ``/metrics`` endpoint
on the FastAPI app exposes them for scraping.

.. note::

   ``prometheus_client`` is an optional dependency — if not installed the
   registry stays inert and no metrics are collected.
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

try:
    import prometheus_client
    from prometheus_client import Counter, Histogram

    _REGISTRY: prometheus_client.CollectorRegistry | None = prometheus_client.REGISTRY
except ImportError:
    _REGISTRY = None
    logger.warning("prometheus_client not installed — agent metrics disabled")

    def Counter(name, documentation, labelnames=None, **_):
        return _NoopMetric()

    def Histogram(name, documentation, labelnames=None, **_):
        return _NoopMetric()


class _NoopMetric:
    """Returned when prometheus_client is unavailable so calling code doesn't branch."""
    def __init__(self, *args, **kwargs):
        pass
    def labels(self, *args, **kwargs):
        return self
    def inc(self, *args, **kwargs): pass
    def observe(self, *args, **kwargs): pass
    def time(self):
        class _noop_ctx:
            def __enter__(self): pass
            def __exit__(self, *a): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): pass
        return _noop_ctx()


# ── Tool-call metrics ───────────────────────────────────────────────────
TOOL_CALL_TOTAL = Counter(
    "agent_tool_calls_total",
    "Total tool calls made by the agentic loop",
    labelnames=["tool", "status"],
)
TOOL_CALL_DURATION = Histogram(
    "agent_tool_call_duration_seconds",
    "Wall-clock time for a single tool call inside the agentic loop",
    labelnames=["tool"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10, 30],
)

# ── Investigation-loop metrics ──────────────────────────────────────────
INVESTIGATION_TOTAL = Counter(
    "agent_investigations_total",
    "Completed investigation runs (incident and ask combined)",
    labelnames=["kind", "status"],   # kind = incident | ask, status = ok | error
)
INVESTIGATION_DURATION = Histogram(
    "agent_investigation_duration_seconds",
    "End-to-end investigation wall-clock time",
    labelnames=["kind"],
    buckets=[1, 2, 5, 10, 20, 30, 60, 120],
)
TOOL_STEPS = Histogram(
    "agent_investigation_tool_steps",
    "How many tool-call steps the loop made before finishing",
    labelnames=["kind"],
    buckets=[0, 1, 2, 3, 4, 5, 6],
)

# ── LLM call metrics ────────────────────────────────────────────────────
LLM_CALL_TOTAL = Counter(
    "agent_llm_calls_total",
    "LLM invocations (ainvoke) from the agentic loop",
    labelnames=["kind"],  # kind = agentic | fallback
)
LLM_CALL_DURATION = Histogram(
    "agent_llm_call_duration_seconds",
    "Per-call LLM latency",
    labelnames=["kind"],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 20, 30, 60],
)

# ── Monitor metrics ────────────────────────────────────────────────────
MONITOR_CYCLES_TOTAL = Counter(
    "agent_monitor_cycles_total",
    "Background monitor poll cycles",
    labelnames=["kind"],  # kind = endpoint | alert_rule | container
)
ALERTS_TOTAL = Counter(
    "agent_alerts_total",
    "Alerts emitted by the background monitor",
    labelnames=["severity", "kind"],  # severity = info | warning | critical, kind = endpoint | promql | container
)

# ── API metrics ─────────────────────────────────────────────────────────
API_REQUESTS_TOTAL = Counter(
    "agent_api_requests_total",
    "HTTP requests served by the FastAPI server",
    labelnames=["method", "path", "status"],
)
API_REQUEST_DURATION = Histogram(
    "agent_api_request_duration_seconds",
    "Request-handling latency",
    labelnames=["method", "path"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5],
)


def _noop_registry() -> object:
    """Return a real or noop registry depending on availability."""
    if _REGISTRY is None:
        return _NoopMetric()
    return _REGISTRY


def generate_latest() -> bytes:
    """Return the Prometheus text-format exposition for all registered metrics."""
    if _REGISTRY is not None:
        from prometheus_client import generate_latest as _gen

        return _gen(_REGISTRY)
    return b"# agent metrics disabled (prometheus_client missing)\n"
