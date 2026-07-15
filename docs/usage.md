# Usage

## Discord commands

| Command                   | Description                                          |
| ------------------------- | ---------------------------------------------------- |
| `!status <service>`       | Check the current status of a service                |
| `!logs <service> [n]`     | Return the last `n` log lines                        |
| `!metrics <service>`      | Return current metrics for a service                 |
| `!incident <service>`     | Run the incident investigation workflow              |
| `!scenario <name>`        | Run a simulated scenario from `scenarios/<name>.yml`  |
| `!ack <incident_id>`      | Acknowledge a stored incident                        |
| `!resolve <incident_id>`  | Resolve a stored incident                            |
| `!health <url>`           | Check reachability and latency of an HTTP endpoint   |

## HTTP API

- `GET /health`
- `GET /services/{service}/status`
- `GET /services/{service}/logs?lines=20`
- `GET /services/{service}/metrics`
- `POST /incidents/{service}`

## Alerting

Use `agent.alerting.discord.send_alert()` inside workflows to post messages to a configured channel.
