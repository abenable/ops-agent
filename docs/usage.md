# Usage

## Discord commands

Commands run in `#agent-commands` (or wherever the bot can read) as slash (`/`) commands.
Verbose commands accept a `raw` option to skip the LLM summary and show the full output.

| Command | Description |
| --- | --- |
| `/status <service>` | Current status of a service via Docker container discovery |
| `/containers [raw]` | List Docker containers grouped by state |
| `/logs <service> [n] [raw]` | Last `n` log lines (default 10) from Loki |
| `/metrics <service> [raw]` | Current metrics for a service from Prometheus |
| `/health <url>` | Reachability and latency of an HTTP endpoint |
| `/watching` | List endpoints configured for background monitoring |
| `/watch <container>` | Add a container to the watch list (status updates + down-alerts) |
| `/unwatch <container>` | Remove a container from the watch list |
| `/watchlist` | List the containers currently being watched |
| `/ask <question>` | Free-form agentic investigation using read-only tools |
| `/incident <service>` | Run the incident investigation workflow; posts summary + incident id, opens an incident thread, and alerts the alert channel |
| `/task <name>` | Run a simulated task from `tasks/<name>.yml` (restricted to the test-tasks channel if configured) |
| `/ack <incident_id>` | Acknowledge a stored incident (and post to its thread) |
| `/resolve <incident_id>` | Resolve a stored incident (and post to its thread) |
| `/menu` | Interactive container picker with Status/Logs/Metrics buttons |
| `/panel` | Service picker with Status/Health/Logs/Metrics/Incident buttons |
| `/info` | Bot info and support links |

## Reply summarisation

Verbose commands (`containers`, `logs`, `metrics`) route their output through the LLM to
produce a short, scannable Discord summary. Pass the `raw` option to bypass the summary
and see the complete output. Short commands (`status`, `health`, `watching`) return raw
output for low latency.

## Conversational replies

Tag the bot in a message or DM it (e.g. `@Oracle why is web slow?`) and it answers through
the same agentic loop as `/ask` — it can call the read-only Prometheus/Loki and Docker tools
to investigate. The prompt also includes environment context (monitored endpoints, configured
channels, Prometheus/Loki URLs, and the available tool list) so answers are grounded in this
deployment. Long replies are split across multiple messages.

## HTTP API

| Method & path | Description |
| --- | --- |
| `GET /health` | Liveness probe → `{"status": "ok"}` |
| `GET /services/{service}/status` | Service status |
| `GET /services/{service}/logs?lines=N` | Recent logs (default `N=10`) |
| `GET /services/{service}/metrics` | Service metrics |
| `GET /health-check?url=...` | Reachability + latency of an HTTP endpoint |
| `POST /incidents/{service}` | Run the incident workflow → `{incident_id, summary}` |
| `POST /incidents/{service}/stream` | SSE stream of the incident investigation |
| `POST /ask/stream` | SSE stream of a free-form agentic question |
| `GET /incidents` | List stored incidents (optional `?status=`) |
| `GET /incidents/{id}` | Fetch an incident by id |
| `GET /containers` | List all Docker containers |
| `GET /metrics` | Prometheus text-format metrics for the agent itself |
| `GET /watch/containers` | Names of the containers currently being watched |
| `PUT /watch/containers/{name}` | Add a container to the watch list |
| `DELETE /watch/containers/{name}` | Remove a container from the watch list |

### Authentication

If `API_KEY` is set, send it on every request:

```bash
curl -H "X-API-Key: $API_KEY" http://localhost:8000/services/web/status
```

If `API_KEY` is unset the API is open — keep `API_HOST=127.0.0.1` in that case.

Interactive docs are available at `/docs` (Swagger UI) when the API is running.

## Background monitoring

The bot runs **three** complementary checks on every `MONITOR_INTERVAL_SECONDS` cycle:

### HTTP endpoint liveness

Set `MONITORED_ENDPOINTS` to a comma-separated list of `name=url` pairs. The bot
polls each endpoint and:

- posts **every** up↔down transition to the status channel, and
- on a healthy→down transition, posts a critical alert to the alert channel and opens a
  threaded incident (running the incident workflow for that endpoint name).

Disabled when `MONITORED_ENDPOINTS` is empty.

### PromQL alert rules

Set `PROMETHEUS_ALERT_RULES` to comma-separated `name=<PromQL>` pairs. Each cycle
the bot evaluates every rule against `PROMETHEUS_URL`. A rule fires when the query
returns one or more series, and the bot alerts only on the first
not-firing → firing transition.

- firing → posts a critical alert to `#alerts` and opens an incident thread.
- recovering → posts an info note to `#status-updates`.
- `PROMETHEUS_TOKEN` is sent as a bearer token when set.

Disabled when `PROMETHEUS_ALERT_RULES` is empty. See
[workflows.md](workflows.md) for the full flow.

### Container watch list

By default the monitor ignores containers. To get status snapshots in `#status-updates` and
down-alerts in `#alerts` for a container, add it to the **watch list** — from Discord with
`/watch <container>` (or the Watch button in `/menu`), or from the web dashboard's container cards
(`＋ watch` toggle). Names match separator-agnostically
(`agent_api` finds `marconi-agent-api`).

- `/watchlist` lists the current selection.
- `/unwatch <container>` (or the toggle again) stops reporting it.
- The periodic snapshot (`STATUS_SNAPSHOT_INTERVAL_SECONDS`) and container down-alerts only
  cover watched containers; everything else stays silent.
- The watch list is persisted in SQLite, so it survives bot restarts.

## Alerting from your own code

```python
from agent.alerting.discord import send_alert
await send_alert(channel_id, "message", bot, severity="warning", title="Heads up")
```

`severity` is one of `info` / `warning` / `critical` and controls the embed color.

## Self-metrics

The agent exposes its own operational metrics at `GET /metrics` in Prometheus
text format. Key metric families include:

| Metric | Type | Description |
| --- | --- | --- |
| `agent_tool_calls_total` | Counter | Tool invocations by name and status |
| `agent_llm_calls_total` | Counter | LLM calls (agentic / fallback) |
| `agent_investigations_total` | Counter | Completed investigations (incident / ask) |
| `agent_investigation_duration_seconds` | Histogram | End-to-end investigation latency |
| `agent_monitor_cycles_total` | Counter | Background monitor poll cycles |
| `agent_alerts_total` | Counter | Alerts emitted by severity and kind |
| `agent_api_requests_total` | Counter | HTTP requests served by method, path, and status |

The `prometheus_client` Python package is required; metrics degrade to a no-op
when it is not installed.
