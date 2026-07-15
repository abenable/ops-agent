# Tools

Controlled tools the agent uses to inspect infrastructure. "Data source" notes whether a tool
returns real data or a placeholder in the current MVP.

| Tool (module) | Signature | Data source |
| --- | --- | --- |
| `tools.services.get_service_status` | `(service) -> dict` | **Stub** — always `{"status": "unknown"}`; not yet wired to a service registry |
| `tools.metrics.get_service_metrics` | `(service) -> dict` | **Prometheus**, falling back to a zeroed stub when unreachable |
| `tools.logs.get_recent_logs` | `(service, lines=10) -> str` | **Loki**, falling back to a stub line when unreachable |
| `tools.health.check_endpoint` | `(url, timeout=5.0) -> dict` | **Real** — HTTP GET, reports reachability, status code, latency |
| `tools.docker.list_containers` | `(all_containers=True) -> list` | **Real** — Docker Engine API (returns `[]` when no socket) |
| `tools.docker.container_logs` | `(container_id, tail=20) -> str` | **Real** — Docker Engine API |
| `tools.docker.restart_container` | `(container_id, timeout=10) -> dict` | **Real** — Docker Engine API |
| `tools.ssh.run_ssh_command` | `(host, command, user) -> dict` | **Real** — runs the system `ssh` binary |
| `tools.ssh.check_server_load` | `(host, user) -> dict` | **Real** — loadavg / free / stat over SSH |
| `tools.ssh.restart_service` | `(host, service, user) -> dict` | **Real** — `systemctl restart` (service name is validated) |
| `tools.incidents.acknowledge_incident` | `(incident_id) -> dict\|None` | SQLite |
| `tools.incidents.resolve_incident` | `(incident_id) -> dict\|None` | SQLite |
| `tools.incidents.list_incidents` | `(status=None, limit=50) -> list` | SQLite |
| `tools.sources.prometheus.query_prometheus` | `(query) -> dict` | Prometheus `/api/v1/query` |
| `tools.sources.prometheus.list_metric_names` | `(match="") -> list[str]` | Prometheus `/api/v1/label/__name__/values` |
| `tools.sources.prometheus.get_label_values` | `(label) -> list[str]` | Prometheus `/api/v1/label/<label>/values` |
| `tools.sources.prometheus.query_prometheus_range` | `(promql, minutes) -> dict` | Prometheus `/api/v1/query_range` |
| `tools.sources.loki.query_loki` | `(query, limit=100) -> dict` | Loki `/loki/api/v1/query` (instant) |
| `tools.sources.loki.query_loki_range` | `(query, minutes, limit=100) -> dict` | Loki `/loki/api/v1/query_range` |
| `tools.query_tools.query_prometheus` | LangChain tool wrapping the instant query | (see above) |
| `tools.query_tools.list_metric_names` | LangChain tool for metric discovery | (see above) |
| `tools.query_tools.get_label_values` | LangChain tool for label discovery | (see above) |
| `tools.query_tools.query_prometheus_range` | LangChain tool for range queries | (see above) |
| `tools.query_tools.query_loki` | LangChain tool wrapping Loki instant query | (see above) |
| `tools.query_tools.query_loki_range` | LangChain tool for Loki range queries | (see above) |

## Agentic query tools

During an investigation (`!incident`, `!ask`, `POST /incidents`) the LLM is given
read-only LangChain tools from `tools.query_tools`. The model decides which
PromQL/LogQL to write and what metadata to fetch first. Results are truncated
and the loop is bounded by `MAX_TOOL_STEPS`.

These tools never mutate infrastructure; Docker/SSH restart tools are kept out
of the agent loop.

## Exposure

- **Chat / API:** status, logs, metrics, HTTP health, and the incident workflow are reachable
  from Discord and/or the API.
- **Library-only:** the Docker and SSH tools are **not** exposed to chat or HTTP. They are
  building blocks for future workflows. `restart_service` validates the systemd unit name
  against `^[A-Za-z0-9._@-]+$` to prevent command injection; `run_ssh_command` requires an
  explicit `user` (no implicit `root`).

## Configuration

- Metrics/logs need `PROMETHEUS_URL` / `LOKI_URL` reachable to return real data.
- The Docker tools read `DOCKER_HOST` (defaults to `unix:///var/run/docker.sock`).
- The SSH tools assume key-based auth is already configured for the target host.
