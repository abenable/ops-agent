"""Read-only LangChain tools the LLM can call during an investigation."""

from langchain_core.tools import tool

from agent.config.settings import settings
from agent.helpers import docker
from agent.helpers.sources import loki, prometheus


@tool
async def list_services() -> str:
    """List known infrastructure targets by their real names: Docker container
    names and configured monitored endpoints. Call this FIRST when you are unsure
    of the exact service name, then use the names it returns for your queries."""
    containers = await docker.list_containers(all_containers=True)
    names = [docker.container_name(c) for c in containers]
    endpoints: list[str] = []
    for pair in settings.monitored_endpoints.split(","):
        if "=" in pair:
            n, u = pair.split("=", 1)
            n, u = n.strip(), u.strip()
            if n and u:
                endpoints.append(f"{n}={u}")
    lines = [
        "Containers: " + (", ".join(names) if names else "(none / docker unreachable)"),
        "Monitored endpoints: "
        + (", ".join(endpoints) if endpoints else "(none configured)"),
    ]
    return "\n".join(lines)[:4000]


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
async def get_loki_label_values(label: str) -> str:
    """List values for a Loki stream label such as 'service' or 'job'. Loki's
    label schema is set by Promtail and is NOT the same as Prometheus's or a
    Docker container name — do not guess a label like 'container'; call this
    first to learn the real label values before writing a LogQL selector."""
    values = await loki.get_label_values(label)
    return "\n".join(values[:250]) if values else f"(no values for label {label})"


@tool
async def query_loki(logql: str, limit: int = 100) -> str:
    """Run an instant LogQL query against Loki. Use this to pull logs the query scopes itself.
    Keep `limit` small; it is clamped to the configured maximum."""
    limit = max(1, min(limit, settings.loki_max_limit))
    return str(await loki.query_loki(logql, limit))[:4000]


@tool
async def query_loki_range(logql: str, minutes: int, limit: int = 100) -> str:
    """Run a LogQL range query over the last `minutes`. Prefer this when the user
    asks for logs over a recent window. The window and limit are clamped."""
    limit = max(1, min(limit, settings.loki_max_limit))
    return str(await loki.query_loki_range(logql, minutes, limit))[:4000]


@tool
async def get_collected_logs(container: str, hours: int = 24, limit: int = 100) -> str:
    """List recent lines from the agent's own collected log store for a watched
    container, covering the last `hours` (default 24, capped at 7 days). This is
    the agent's local log history, separate from Loki and from live Docker logs —
    use it when Loki has no matching stream for the service, before falling back
    to docker_logs. Only covers containers on the watch list."""
    from datetime import datetime, timedelta, timezone

    from agent.logstore.reader import iter_lines
    from agent.memory.repository import list_watched_containers
    from agent.helpers.normalize import normalize as _normalize

    hours = max(1, min(hours, 7 * 24))
    limit = max(1, min(limit, 500))
    needle = _normalize(container)
    target = next(
        (name for name in list_watched_containers() if needle in _normalize(name)),
        None,
    )
    if target is None:
        return f"'{container}' is not a watched container; the collected log store only covers watched containers."
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    lines = list(iter_lines(target, since=since))[-limit:]
    if not lines:
        return f"No collected log lines for '{target}' in the last {hours}h."
    return "\n".join(f"[{r['ts']}] {r['raw']}" for r in lines)[:4000]


@tool
async def docker_status(container: str) -> str:
    """Return the state of a Docker container (read-only): state, status, image.
    Use a container name returned by list_services. Matching is separator-agnostic
    so 'agent_api' matches 'marconi-agent-api'."""
    target = await docker.find_container(container)
    if target is None:
        return f"(no container matching '{container}')"
    name = docker.container_name(target)
    return (
        f"{name}: state={target.get('State')}, "
        f"status={target.get('Status')}, image={target.get('Image')}"
    )


@tool
async def docker_logs(container: str, tail: int = 50) -> str:
    """Fetch the last `tail` lines of a Docker container's stdout/stderr logs
    (read-only). Use this when Loki has no logs for a container, or to read a
    container's own output directly. Use a container name from list_services;
    `tail` is capped at 200."""
    tail = max(1, min(tail, 200))
    target = await docker.find_container(container)
    if target is None:
        return f"(no container matching '{container}')"
    raw = await docker.container_logs(target.get("Id") or docker.container_name(target), tail=tail)
    # Strip Docker's stream-framing control bytes so the output is readable.
    cleaned = "".join(c for c in raw if c.isprintable() or c in "\n\t")
    return cleaned[:4000] or "(no logs)"
