# Usage

## Discord commands

All commands use the `!` prefix and run in `#agent-commands` (or wherever the bot can read).

| Command | Description |
| --- | --- |
| `!status <service>` | Current status of a service |
| `!logs <service> [n]` | Last `n` log lines (default 10) |
| `!metrics <service>` | Current metrics for a service |
| `!health <url>` | Reachability and latency of an HTTP endpoint |
| `!incident <service>` | Run the incident investigation workflow; posts summary + incident id, opens an incident thread, and alerts the alert channel |
| `!scenario <name>` | Run a simulated scenario from `scenarios/<name>.yml` (restricted to the test-scenarios channel if configured) |
| `!ack <incident_id>` | Acknowledge a stored incident (and post to its thread) |
| `!resolve <incident_id>` | Resolve a stored incident (and post to its thread) |

## HTTP API

| Method & path | Description |
| --- | --- |
| `GET /health` | Liveness probe → `{"status": "ok"}` |
| `GET /services/{service}/status` | Service status |
| `GET /services/{service}/logs?lines=N` | Recent logs (default `N=10`) |
| `GET /services/{service}/metrics` | Service metrics |
| `GET /health-check?url=...` | Reachability + latency of an HTTP endpoint |
| `POST /incidents/{service}` | Run the incident workflow → `{incident_id, summary}` |

### Authentication

If `API_KEY` is set, send it on every request:

```bash
curl -H "X-API-Key: $API_KEY" http://localhost:8000/services/web/status
```

If `API_KEY` is unset the API is open — keep `API_HOST=127.0.0.1` in that case.

Interactive docs are available at `/docs` (Swagger UI) when the API is running.

## Background monitoring

Set `MONITORED_ENDPOINTS` to a comma-separated list of `name=url` pairs. Every
`MONITOR_INTERVAL_SECONDS` the bot polls each endpoint and:

- posts **every** up↔down transition to the status channel, and
- on a healthy→down transition, posts a critical alert to the alert channel and opens a
  threaded incident (running the incident workflow for that endpoint name).

The monitor is disabled when `MONITORED_ENDPOINTS` is empty. See
[workflows.md](workflows.md) for the full flow.

## Alerting from your own code

```python
from agent.alerting.discord import send_alert
await send_alert(channel_id, "message", bot, severity="warning", title="Heads up")
```

`severity` is one of `info` / `warning` / `critical` and controls the embed color.
