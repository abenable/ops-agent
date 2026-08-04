# Usage

## Discord commands

Commands run in `#agent-commands` (or wherever the bot can read) and have both a prefix (`!`)
and a slash (`/`) form. Verbose commands accept a `raw` flag/option to skip the LLM summary and
show the full output.

| Command | Description |
| --- | --- |
| `!status <service>` / `/status` | Current status of a service via Docker container discovery |
| `!containers [raw]` / `/containers [raw]` | List Docker containers grouped by state |
| `!logs <service> [n] [raw]` / `/logs ...` | Last `n` log lines (default 10) from Loki |
| `!metrics <service> [raw]` / `/metrics ...` | Current metrics for a service from Prometheus |
| `!health <url>` / `/health` | Reachability and latency of an HTTP endpoint |
| `!watching` / `/watching` | List endpoints configured for background monitoring |
| `!watch <container>` / `/watch` | Add a container to the watch list (status updates + down-alerts) |
| `!unwatch <container>` / `/unwatch` | Remove a container from the watch list |
| `!watchlist` / `/watchlist` | List the containers currently being watched |
| `!ask <question>` / `/ask` | Free-form agentic investigation using read-only tools |
| `!incident <service>` / `/incident` | Run the incident investigation workflow; posts summary + incident id, opens an incident thread, and alerts the alert channel |
| `!scenario <name>` / `/scenario` | Run a simulated scenario from `scenarios/<name>.yml` (restricted to the test-scenarios channel if configured) |
| `!ack <incident_id>` / `/ack` | Acknowledge a stored incident (and post to its thread) |
| `!resolve <incident_id>` / `/resolve` | Resolve a stored incident (and post to its thread) |
| `!menu` / `/menu` | Interactive container picker with Status/Logs/Metrics buttons |
| `!panel` / `/panel` | Service picker with Status/Health/Logs/Metrics/Incident buttons |
| `!info` / `/info` | Bot info and support links |

## Reply summarisation

Verbose commands (`containers`, `logs`, `metrics`) route their output through the LLM to
produce a short, scannable Discord summary. Pass `raw` (a flag for prefix commands, an option
for slash commands) to bypass the summary and see the complete output. Short commands
(`status`, `health`, `watching`) return raw output for low latency.

## Conversational replies

Tag the bot in a message or DM it (e.g. `@Oracle why is web slow?`) and it answers through
the same agentic loop as `!ask` — it can call the read-only Prometheus/Loki and Docker tools
to investigate. The prompt also includes environment context (monitored endpoints, configured
channels, Prometheus/Loki URLs, and the available tool list) so answers are grounded in this
deployment. Long replies are split across multiple messages. Prefix commands (`!status`,
`!incident`, etc.) still work as usual.

## HTTP API

| Method & path | Description |
| --- | --- |
| `GET /health` | Liveness probe → `{"status": "ok"}` |
| `GET /services/{service}/status` | Service status |
| `GET /services/{service}/logs?lines=N` | Recent logs (default `N=10`) |
| `GET /services/{service}/metrics` | Service metrics |
| `GET /health-check?url=...` | Reachability + latency of an HTTP endpoint |
| `POST /incidents/{service}` | Run the incident workflow → `{incident_id, summary}` |
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

The bot runs two complementary checks on every `MONITOR_INTERVAL_SECONDS` cycle.

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
`!watch <container>` / `/watch <container>` (or the Watch button in `!menu`), or from the web
dashboard's container cards (`＋ watch` toggle). Names match separator-agnostically
(`agent_api` finds `marconi-agent-api`).

- `!watchlist` / `/watchlist` lists the current selection.
- `!unwatch <container>` / `/unwatch <container>` (or the toggle again) stops reporting it.
- The periodic snapshot (`STATUS_SNAPSHOT_INTERVAL_SECONDS`) and container down-alerts only
  cover watched containers; everything else stays silent.
- The watch list is persisted in SQLite, so it survives bot restarts.

## Alerting from your own code

```python
from agent.alerting.discord import send_alert
await send_alert(channel_id, "message", bot, severity="warning", title="Heads up")
```

`severity` is one of `info` / `warning` / `critical` and controls the embed color.
