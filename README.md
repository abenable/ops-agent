# Marconi Infrastructure Operations Agent

An MVP infrastructure-operations agent that lives in Discord. It answers operator questions
about services (status, logs, metrics, HTTP health), runs an LLM-assisted incident
investigation workflow, watches endpoints in the background and raises alerts, and tracks
incidents in a small SQLite store — all driven from a Discord chat interface with a FastAPI
backend alongside.

Built during the Implementation Phase (Weeks 5–8) of the Marconi industrial training.

## Features

- **Discord interface** — prefix (`!`) and slash (`/`) commands for status, logs, metrics,
  health, incident investigation, free-form questions, scenario simulation, and incident
  acknowledge/resolve; interactive container menu and service panel with action buttons;
  conversational replies when you @mention or DM the bot. Verbose output is summarised by the
  LLM for clean replies, with a `raw` opt-out.
- **Agentic investigation** — the LLM discovers real service names, writes its own PromQL/LogQL
  through read-only Prometheus and Loki tools (metric/label discovery, instant + range queries),
  and inspects containers with read-only Docker status/logs tools, in a bounded tool-calling
  loop. Service names match separator-agnostically (`agent_api` finds `marconi-agent-api`).
- **Background monitoring** — a poll loop runs two complementary checks each cycle: HTTP
  endpoint liveness, and PromQL alert-rule evaluation. It posts status changes and down-alerts
  to Discord and auto-opens a threaded incident on escalation. Container status is only reported
  for containers explicitly selected via `!watch`/`!unwatch` or the web dashboard's watch toggle.
- **Incident tracking** — SQLite-backed incidents with acknowledge / resolve lifecycle, an
  optional Discord thread per incident, and persistent Acknowledge/Resolve buttons on the
  incident thread message.
- **Backend API** — FastAPI service exposing the same tools over HTTP, with optional
  shared-secret auth.
- **Monitoring sources** — Prometheus (metrics) and Loki (logs) with optional bearer-token
  auth, and graceful fallback to stubs when a source is unreachable.
- **Self-hosted LLM** — points at any OpenAI-compatible endpoint (Ollama, vLLM,
  llama.cpp server, a hosted gateway). Tool-calling support required for agentic investigation
  (static fallback otherwise).

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

Each command has both a prefix (`!`) and a slash (`/`) form. Verbose commands accept a `raw`
flag/option to skip the LLM summary and show the full output.

| Command | Description |
| --- | --- |
| `!status <service>` / `/status` | Current status of a service via Docker container discovery |
| `!containers [raw]` / `/containers [raw]` | List Docker containers grouped by state |
| `!logs <service> [n] [raw]` / `/logs ...` | Last `n` log lines (default 10) from Loki |
| `!metrics <service> [raw]` / `/metrics ...` | Current metrics for a service from Prometheus |
| `!health <url>` / `/health` | Reachability + latency of an HTTP endpoint |
| `!watching` / `/watching` | List endpoints configured for background monitoring |
| `!watch <container>` / `/watch` | Add a container to the watch list (status updates + down-alerts) |
| `!unwatch <container>` / `/unwatch` | Remove a container from the watch list |
| `!watchlist` / `/watchlist` | List the containers currently being watched |
| `!ask <question>` / `/ask` | Free-form agentic investigation using read-only tools |
| `!incident <service>` / `/incident` | Run the incident investigation workflow |
| `!scenario <name>` / `/scenario` | Run a simulated scenario from `scenarios/<name>.yml` |
| `!ack <incident_id>` / `/ack` | Acknowledge a stored incident |
| `!resolve <incident_id>` / `/resolve` | Resolve a stored incident |
| `!menu` / `/menu` | Interactive container picker with Status/Logs/Metrics buttons |
| `!panel` / `/panel` | Service picker with Status/Health/Logs/Metrics/Incident buttons |
| `!info` / `/info` | Bot info and support links |

You can also **@mention** or DM the bot with a question; it answers through the same agentic loop.

## HTTP API

| Method & path | Description |
| --- | --- |
| `GET /health` | Liveness probe |
| `GET /services/{service}/status` | Service status |
| `GET /services/{service}/logs?lines=N` | Recent logs |
| `GET /services/{service}/metrics` | Service metrics |
| `GET /health-check?url=...` | Reachability + latency of an endpoint |
| `POST /incidents/{service}` | Run the incident workflow, returns `{incident_id, summary}` |
| `GET /watch/containers` | Names of the containers currently being watched |
| `PUT /watch/containers/{name}` | Add a container to the watch list |
| `DELETE /watch/containers/{name}` | Remove a container from the watch list |

If `API_KEY` is set, every request must send an `X-API-Key` header. If it is unset, the API
is unauthenticated (bind to `127.0.0.1`, the default).

## Discord channels

The bot maps its output to purpose-specific channels (all optional; a feature is simply
inactive when its channel id is unset). See [docs/discord-channels.md](docs/discord-channels.md).

| Channel | Role |
| --- | --- |
| `#agent-commands` | Where operators run commands |
| `#alerts` | Down-alerts and incident notifications (embeds, severity-colored) |
| `#status-updates` | Every up/down transition and periodic status snapshot for **watched** containers |
| `#incidents` | One thread per incident, with ack/resolve updates |
| `#agent-logs` | WARNING+ bot/backend logs (optional) |
| `#test-scenarios` | Safe channel to trigger `!scenario` runs |

## Project structure

```
.
├── main.py                  # Backwards-compatible launcher
├── src/agent/
│   ├── bot/                 # Discord client, prefix + slash commands, menus, summarize, monitor
│   ├── api/                 # FastAPI server and routes
│   ├── llm/                 # Self-hosted LLM client
│   ├── tools/               # Controlled tools (status/logs/metrics/health/docker/ssh)
│   │   ├── sources/         # Prometheus and Loki query helpers
│   │   ├── normalize.py     # Separator-agnostic service-name matching
│   │   └── query_tools.py   # Read-only LangChain tools the LLM calls during investigations
│   ├── workflows/           # Incident investigation (agentic loop) and reporting
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

- [Goals](docs/goals.md) — project objectives and current deliverable status
- [Setup](docs/setup.md) — install, configuration reference, Docker
- [Usage](docs/usage.md) — commands, API, monitoring
- [Architecture](docs/architecture.md) — components and data flow
- [Tools](docs/tools.md) — what each tool does and its data source
- [Workflows](docs/workflows.md) — incident, monitoring, and reporting flows
- [Discord channels](docs/discord-channels.md) — channel-to-feature mapping

## Limitations

This is an MVP built for a controlled environment. Known limitations:

- **Metrics/logs depend on Prometheus/Loki** — when those sources are unreachable, the tools
  fall back to placeholder values rather than failing loudly. The read-only Docker logs tool
  covers containers Prometheus/Loki do not tag.
- **Agentic investigation needs a tool-calling model** — if the configured LLM does not support
  OpenAI-style tool calls, investigations degrade to a static status+metrics+logs summary. The
  bot logs a warning at startup when tool calls are unsupported.
- **Alerting is single-environment** — one Prometheus/Loki pair; no named multi-source registry.
- **Monitor state is in memory** — alert de-duplication resets when the bot restarts, and the
  monitor loop is (re)started from `on_ready`.
- **Incident action buttons do not survive restarts** — the Acknowledge/Resolve buttons on an
  incident thread use `timeout=None` so they never expire while the bot runs, but stop listening
  after a redeploy. The `!ack`/`!resolve` (and `/ack`/`/resolve`) commands remain as fallbacks.
- **No RBAC** — any member who can see `#agent-commands` can run any command; SSH/Docker
  mutation tools are library-only and not exposed to chat or the LLM.
- **Single-node SQLite** — fine for one bot instance; not built for concurrent writers.

## Future improvements

- Named multi-environment monitoring sources (prod/staging registry).
- Re-register incident action views on startup from open incidents in SQLite, so the buttons
  keep working after a redeploy.
- Alertmanager webhook receiver (hosted in the bot process) as an alternative to in-bot polling.
- Persist monitor/alert state so de-duplication survives restarts.
- Role-based command permissions and an allowlist for SSH/Docker actions.
- Human-in-the-loop approval before any Docker/SSH write action is executed.
