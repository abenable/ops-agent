"""Read-only view of the cluster's nodes: Docker reachability plus node metrics from Prometheus.

A node's name is its ``NODES`` name, the ``node`` label on its Prometheus targets and
its Loki streams, and the prefix of its containers' names (``pi1/cadvisor``).
"""

import asyncio

from langchain_core.tools import tool

from agent.config.settings import settings
from agent.normalize import AmbiguousName, resolve_one
from agent.tools import docker, prometheus

# One instant query per column; each returns a vector labelled by `node`.
QUERIES = {
    "up": 'up{job="node"}',
    "cpu_percent": '100 * (1 - avg by (node) (rate(node_cpu_seconds_total{mode="idle"}[2m])))',
    "memory_percent": "100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)",
    "temperature_c": "max by (node) (node_thermal_zone_temp)",
    "undervoltage": "max by (node) (rpi_undervoltage_now)",
    "throttled": "max by (node) (rpi_throttled_now)",
    "power_mw": 'sum by (node) (jetson_rail_power_mw{rail=~"POM_5V_IN|VDD_IN"})',
}


async def _per_node(promql: str) -> dict[str, float]:
    try:
        payload = await prometheus.query(promql)
    except Exception:  # noqa: BLE001 - a missing metric is a blank column, not a failure
        return {}
    out: dict[str, float] = {}
    for series in (payload.get("data") or {}).get("result") or []:
        if name := series.get("metric", {}).get("node"):
            out[name] = round(float(series["value"][1]), 1)
    return out


async def node_rows(by_node: dict[str, list[dict] | None] | None = None) -> list[dict]:
    """One row per node: Docker reachability, container counts and the latest metrics.

    A value is None when it is unknown (no Prometheus, or the node has no such sensor).
    """
    metrics: dict[str, dict[str, float]] = {}
    if settings.prometheus_url:
        results = await asyncio.gather(*(_per_node(q) for q in QUERIES.values()))
        metrics = dict(zip(QUERIES, results, strict=True))
    if by_node is None:
        by_node = await docker.containers_by_node()
    names = list(by_node) + sorted({n for col in metrics.values() for n in col} - set(by_node))
    rows = []
    for name in names:
        containers = by_node.get(name)
        row = {
            "name": name,
            "docker_reachable": None if name not in by_node else containers is not None,
            "containers": None if containers is None else len(containers),
            "running": None if containers is None else sum(c.get("State") == "running" for c in containers),
        }
        for column, values in metrics.items():
            row[column] = values.get(name)
        if "up" in row and row["up"] is not None:
            row["up"] = row["up"] == 1
        row["down"] = is_down(row)
        rows.append(row)
    return rows


def is_down(row: dict) -> bool:
    """Down when Prometheus can't scrape node-exporter, or, without Prometheus, Docker can't be reached."""
    if row.get("up") is not None:
        return not row["up"]
    return row.get("docker_reachable") is False


def _line(row: dict) -> str:
    parts = [f"`{row['name']}`: {'DOWN' if row['down'] else 'up'}"]
    if row["docker_reachable"] is False:
        parts.append("docker unreachable")
    elif row["containers"] is not None:
        parts.append(f"{row['running']}/{row['containers']} containers running")
    units = {"cpu_percent": "CPU {}%", "memory_percent": "memory {}%", "temperature_c": "{} °C", "power_mw": "{} mW"}
    parts += [fmt.format(row[k]) for k, fmt in units.items() if row.get(k) is not None]
    if row.get("undervoltage"):
        parts.append("UNDERVOLTAGE now")
    if row.get("throttled"):
        parts.append("THROTTLED now")
    return ", ".join(parts)


@tool
async def list_nodes() -> str:
    """List the cluster's nodes (machines) with health: up or down, Docker reachable, containers running, CPU, memory, temperature, Pi undervoltage/throttling and Jetson power draw. Call this when containers are missing or several fail at once, to tell a node fault from a container fault."""
    rows = await node_rows()
    return "\n".join(_line(r) for r in rows) or "(no nodes configured)"


@tool
async def node_status(node: str) -> str:
    """One node's health (as in list_nodes) plus every container on it with its state. Use a node name from list_nodes."""
    by_node = await docker.containers_by_node()
    rows = await node_rows(by_node)
    try:
        row = resolve_one(node, rows, lambda r: r["name"], kind="nodes")
    except AmbiguousName as exc:
        return f"({exc})"
    if row is None:
        return f"(no node matching '{node}'; known: {', '.join(r['name'] for r in rows)})"
    lines = [_line(row)]
    containers = by_node.get(row["name"]) or []
    lines += [f"- `{docker.container_name(c)}`: {c.get('State')} ({c.get('Status', '')})" for c in containers]
    return "\n".join(lines)[:4000]
