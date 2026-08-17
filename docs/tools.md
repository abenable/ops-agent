# Agent tools

The LLM reaches infrastructure data exclusively through these ten tools
(`src/agent/tools/`, collected in `ALL_TOOLS`). Each tool is a small client
function plus a LangChain `@tool` wrapper; descriptions below are the
docstrings the model actually sees when deciding what to call.

## Docker (`tools/docker.py`, via the Engine API on the local socket)

| Tool | What the model is told |
| --- | --- |
| `list_services()` | List known infrastructure targets by their real names: Docker container names and configured monitored endpoints. Called FIRST when the exact service name is unknown. |
| `docker_status(container)` | State of a container: state, status, image. Matching is separator-agnostic (`agent_api` matches `marconi-agent-api`); a partial name matching several containers is rejected with the candidate list instead of guessing. |
| `docker_logs(container, tail=50)` | Last `tail` lines of a container's stdout/stderr; `tail` capped at 200. Fallback when Loki has no logs for the container. |

## Prometheus (`tools/prometheus.py`, against `PROMETHEUS_URL`)

| Tool | What the model is told |
| --- | --- |
| `query_prometheus(promql)` | Instant PromQL query for current values. |
| `list_metric_names(match="")` | Discover available metric names before writing a query. |
| `get_label_values(label)` | Discover valid label values (`service`, `job`, `instance`, ...) before querying. |
| `query_prometheus_range(promql, minutes)` | Range query for trends; the window is clamped to `RANGE_MAX_HOURS`. |

## Loki (`tools/loki.py`, against `LOKI_URL`)

| Tool | What the model is told |
| --- | --- |
| `get_loki_label_values(label)` | Discover Loki's stream-label values first — Loki's schema is set by Promtail and is NOT the same as Prometheus's or Docker names. |
| `query_loki(logql, limit=100)` | Log query scoped to a short recent window; `limit` clamped to `LOKI_MAX_LIMIT`. |
| `query_loki_range(logql, minutes, limit=100)` | Range query over the last `minutes`; window and limit clamped. |

## Safety boundary

- Every tool is **read-only**. There is deliberately no restart/exec/config
  tool, so the model cannot affect infrastructure — it can only recommend
  actions for a human operator.
- Names never reach a shell: Docker access goes through the Engine API over
  the local socket, Prometheus/Loki through HTTP GET only. Label names are
  validated against `[A-Za-z_][A-Za-z0-9_]*` before they enter a URL path.
  This matters because tool arguments are chosen by the model, from content
  the model just read — an argv would be an injection path, a URL path is not.
- The Docker socket mount is **not** what makes this safe. `:ro` in compose
  only makes the socket file read-only; the Engine API behind it stays
  writable, and socket access is root-equivalent on the host. The boundary is
  that `ALL_TOOLS` contains no mutating call — anything with that socket could
  do more, so keep it off any component that does not need it.
- Outputs are truncated (≈4 KB per call) and the loop is bounded by
  `MAX_TOOL_STEPS`, so a confused model cannot runaway-query the backends.
