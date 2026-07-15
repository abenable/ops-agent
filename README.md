# Marconi Infrastructure Operations Agent

An MVP infrastructure-operations agent that lives in Discord. It answers operator questions
about services (status, logs, metrics, HTTP health), runs an LLM-assisted incident
investigation workflow, watches endpoints in the background and raises alerts, and tracks
incidents in a small SQLite store — all driven from a Discord chat interface with a FastAPI
backend alongside.

Built during the Implementation Phase (Weeks 5–8) of the Marconi industrial training.

## Features

- **Discord interface** — prefix commands for status, logs, metrics, health, incident
  investigation, scenario simulation, and incident acknowledge/resolve.
- **Background monitoring** — a poll loop checks configured HTTP endpoints and posts status
  changes and down-alerts to Discord, auto-opening a threaded incident on escalation.
- **Incident workflow** — collects service status + metrics + logs, asks a self-hosted
  (OpenAI-compatible) LLM for a summary, and persists it.
- **Incident tracking** — SQLite-backed incidents with acknowledge / resolve lifecycle and an
  optional Discord thread per incident.
- **Backend API** — FastAPI service exposing the same tools over HTTP, with optional
  shared-secret auth.
- **Monitoring sources** — Prometheus (metrics) and Loki (logs) helpers, with graceful
  fallback to stubs when a source is unreachable.
- **Self-hosted LLM** — points at any OpenAI-compatible endpoint (Ollama, vLLM,
  llama.cpp server, a hosted gateway).

## Quick start

```bash
uv sync
cp .env.example .env
# edit .env: at minimum set DISCORD_BOT_TOKEN and your LLM endpoint
python -m agent bot        # run the Discord bot
python -m agent api        # or run the HTTP API
```

See [docs/setup.md](docs/setup.md) for the full configuration reference and Docker usage.

## Discord commands

| Command | Description |
| --- | --- |
| `!status <service>` | Current status of a service |
| `!logs <service> [n]` | Last `n` log lines (default 10) |
| `!metrics <service>` | Current metrics for a service |
| `!health <url>` | Reachability + latency of an HTTP endpoint |
| `!incident <service>` | Run the incident investigation workflow |
| `!scenario <name>` | Run a simulated scenario from `scenarios/<name>.yml` |
| `!ack <incident_id>` | Acknowledge a stored incident |
| `!resolve <incident_id>` | Resolve a stored incident |

## HTTP API

| Method & path | Description |
| --- | --- |
| `GET /health` | Liveness probe |
| `GET /services/{service}/status` | Service status |
| `GET /services/{service}/logs?lines=N` | Recent logs |
| `GET /services/{service}/metrics` | Service metrics |
| `GET /health-check?url=...` | Reachability + latency of an endpoint |
| `POST /incidents/{service}` | Run the incident workflow, returns `{incident_id, summary}` |

If `API_KEY` is set, every request must send an `X-API-Key` header. If it is unset, the API
is unauthenticated (bind to `127.0.0.1`, the default).

## Discord channels

The bot maps its output to purpose-specific channels (all optional; a feature is simply
inactive when its channel id is unset). See [docs/discord-channels.md](docs/discord-channels.md).

| Channel | Role |
| --- | --- |
| `#agent-commands` | Where operators run commands |
| `#alerts` | Down-alerts and incident notifications (embeds, severity-colored) |
| `#status-updates` | Every up/down transition detected by the monitor |
| `#incidents` | One thread per incident, with ack/resolve updates |
| `#agent-logs` | WARNING+ bot/backend logs (optional) |
| `#test-scenarios` | Safe channel to trigger `!scenario` runs |

## Project structure

```
.
├── main.py                  # Backwards-compatible launcher
├── src/agent/
│   ├── bot/                 # Discord client, commands, background monitor
│   ├── api/                 # FastAPI server and routes
│   ├── llm/                 # Self-hosted LLM client
│   ├── tools/               # Controlled tools (status/logs/metrics/health/docker/ssh)
│   │   └── sources/         # Prometheus and Loki query helpers
│   ├── workflows/           # Incident investigation and reporting
│   ├── storage/             # SQLite incident repository
│   ├── alerting/            # Discord alert + incident-thread helpers
│   └── config/              # Environment-based settings
├── tests/                   # Test suite
├── scenarios/               # Simulated infrastructure issues (yml)
├── docs/                    # setup, usage, architecture, workflows, tools, channels
└── data/                    # SQLite database
```

## Testing

```bash
uv run pytest             # unit + smoke tests (no external services needed)
uv run pytest -m integration   # live checks (needs a real LLM / Discord token)
```

## Documentation

- [Setup](docs/setup.md) — install, configuration reference, Docker
- [Usage](docs/usage.md) — commands, API, monitoring
- [Architecture](docs/architecture.md) — components and data flow
- [Tools](docs/tools.md) — what each tool does and its data source
- [Workflows](docs/workflows.md) — incident, monitoring, and reporting flows
- [Discord channels](docs/discord-channels.md) — channel-to-feature mapping

## Limitations

This is an MVP built for a controlled environment. Known limitations:

- **`!status` is a stub** — always returns `unknown`; it is not yet wired to a real service
  registry or orchestrator.
- **Metrics/logs depend on Prometheus/Loki** — when those sources are unreachable, the tools
  fall back to placeholder values rather than failing loudly.
- **Monitoring is HTTP-only** — the background loop checks endpoint reachability, not metric
  thresholds; anomaly detection beyond up/down is not implemented.
- **Monitor state is in memory** — alert de-duplication resets when the bot restarts.
- **No RBAC** — any member who can see `#agent-commands` can run any command; SSH/Docker
  tools are library-only and not exposed to chat.
- **Single-node SQLite** — fine for one bot instance; not built for concurrent writers.
- **Prefix commands, not slash commands** — no autocomplete; commands use the `!` prefix.

## Future improvements

- Wire `!status` to a real service inventory (Docker/systemd/orchestrator).
- Metric-threshold and error-rate alerting in the monitor, not just reachability.
- Slash-command interface with autocomplete (`discord.app_commands`).
- Persist monitor/alert state so de-duplication survives restarts.
- Role-based command permissions and an allowlist for SSH/Docker actions.
- Richer workflow orchestration (e.g. LangGraph) with tool-calling by the LLM.
