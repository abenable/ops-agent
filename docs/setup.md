# Setup

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- A Discord bot token and a server to test in ([Discord Developer Portal](https://discord.com/developers/applications))
- A self-hosted LLM exposing an OpenAI-compatible chat endpoint (e.g. Ollama, vLLM,
  llama.cpp server), or any OpenAI-compatible gateway

## Installation

```bash
uv sync            # runtime dependencies
uv sync --dev      # also install dev dependencies (pytest)
```

## Configuration

Copy the example env file and fill in your values:

```bash
cp .env.example .env
```

### Environment reference

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `DISCORD_BOT_TOKEN` | yes (bot) | — | Bot token; the bot refuses to start without it |
| `DISCORD_GUILD_ID` | no | — | Server id (reserved for future scoping) |
| `DISCORD_ALERT_CHANNEL_ID` | no | — | Channel for down-alerts / incident notifications |
| `DISCORD_INCIDENT_CHANNEL_ID` | no | — | Channel where per-incident threads are opened |
| `DISCORD_STATUS_CHANNEL_ID` | no | — | Channel for up/down status transitions |
| `DISCORD_LOG_CHANNEL_ID` | no | — | Channel for WARNING+ bot/backend logs |
| `DISCORD_TEST_SCENARIOS_CHANNEL_ID` | no | — | Restricts `!scenario` to this channel |
| `MONITORED_ENDPOINTS` | no | *(empty)* | Comma-separated `name=url` pairs the monitor polls; empty disables the monitor |
| `MONITOR_INTERVAL_SECONDS` | no | `60` | Poll interval (floored at 10s) |
| `LLM_BASE_URL` | yes (LLM) | `http://localhost:11434/v1` | OpenAI-compatible base URL |
| `LLM_MODEL` | yes (LLM) | `mistral` | Model name |
| `LLM_API_KEY` | no | — | API key for the LLM endpoint (many local servers ignore it) |
| `API_KEY` | no | *(empty)* | If set, the HTTP API requires an `X-API-Key` header |
| `API_HOST` | no | `127.0.0.1` | API bind address (use `0.0.0.0` only behind a trusted network) |
| `API_PORT` | no | `8000` | API port |
| `PROMETHEUS_URL` | no | `http://localhost:9090` | Prometheus base URL for metrics |
| `LOKI_URL` | no | `http://localhost:3100` | Loki base URL for logs |
| `DATABASE_URL` | no | `sqlite:///data/agent.db` | SQLite database location |

Example `MONITORED_ENDPOINTS`: `api=http://localhost:8000/health, site=https://example.com`

To get a Discord channel id: enable **Developer Mode** (User Settings → Advanced), then
right-click a channel → **Copy ID**. Enable the **Message Content Intent** for your bot in the
Developer Portal — the prefix commands depend on it.

## Run

```bash
# Discord bot (starts the background monitor and command handlers)
python -m agent bot

# HTTP API
python -m agent api

# One-shot incident workflow (prints incident id + summary)
python -m agent incident --service web

# Print a stored incident report
python -m agent report --incident-id <id>
```

## Docker

Build and run both services (API + bot):

```bash
docker compose up --build
```

Run only one service:

```bash
docker compose up --build api
docker compose up --build bot
```

The `api` service exposes port `8000` and has a healthcheck; the `bot` service waits until the
API healthcheck passes. Both mount `./data` so the SQLite database persists across restarts.
To let the Docker tools reach the host daemon, uncomment the docker-socket volume in
`docker-compose.yml`.
