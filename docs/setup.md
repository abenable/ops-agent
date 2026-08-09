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
| `DISCORD_STATUS_CHANNEL_ID` | no | — | Channel for status transitions + periodic snapshots of watched containers |
| `DISCORD_LOG_CHANNEL_ID` | no | — | Channel for WARNING+ bot/backend logs |
| `DISCORD_TEST_TASKS_CHANNEL_ID` | no | — | Restricts `/task` to this channel |
| `MONITORED_ENDPOINTS` | no | *(empty)* | Comma-separated `name=url` pairs the monitor polls; empty disables the monitor |
| `MONITOR_INTERVAL_SECONDS` | no | `60` | Poll interval (floored at 10s) |
| `STATUS_SNAPSHOT_INTERVAL_SECONDS` | no | `3600` | Cadence for periodic watched-container status snapshot in `#status-updates` |
| `LLM_BASE_URL` | yes (LLM) | `http://localhost:11434/v1` | OpenAI-compatible base URL |
| `LLM_MODEL` | yes (LLM) | `mistral` | Model name |
| `LLM_API_KEY` | no | — | API key for the LLM endpoint (many local servers ignore it) |
| `LLM_PROVIDER` | no | *(empty)* | Local provider selector: `""` (default), `"ollama"`, or `"vllm"` |
| `OLLAMA_BASE_URL` | no | `http://localhost:11434/v1` | Ollama server base URL |
| `OLLAMA_MODEL` | no | `gemma4:e4b` | Ollama model name |
| `VLLM_BASE_URL` | no | `http://localhost:8001/v1` | vLLM server base URL |
| `VLLM_MODEL` | no | `Qwen/Qwen2.5-1.5B-Instruct` | vLLM model name |
| `API_KEY` | no | *(empty)* | If set, the HTTP API requires an `X-API-Key` header |
| `API_HOST` | no | `127.0.0.1` | API bind address (use `0.0.0.0` only behind a trusted network) |
| `API_PORT` | no | `8000` | API port |
| `WEB_ORIGIN` | no | `http://localhost:5173` | CORS-allowed origin for the web UI |
| `PROMETHEUS_URL` | no | `http://localhost:9090` | Prometheus base URL for metrics |
| `PROMETHEUS_TOKEN` | no | *(empty)* | Optional bearer token for Prometheus |
| `LOKI_URL` | no | `http://localhost:3100` | Loki base URL for logs |
| `LOKI_TOKEN` | no | *(empty)* | Optional bearer token for Loki |
| `MAX_TOOL_STEPS` | no | `6` | Bound on the number of LLM tool calls per investigation |
| `LOKI_MAX_LIMIT` | no | `500` | Maximum Loki log lines a single tool call may request |
| `RANGE_MAX_HOURS` | no | `6` | Maximum Prometheus range-query window in hours |
| `DOCKER_MONITOR` | no | `false` | Poll containers each cycle and alert on a running→stopped transition (Docker-only alerting) |
| `DOCKER_NAME_FILTER` | no | *(empty)* | Alert on containers whose name contains this substring; empty = every container. `/watch` adds out-of-filter containers |
| `REMEDIATION_ENABLED` | no | `true` | Global kill switch for the remediation agent |
| `REMEDIATION_APPROVAL_TTL_SECONDS` | no | `300` | Seconds a proposed action stays approvable before auto-expiry |
| `DATABASE_URL` | no | `sqlite:///data/agent.db` | SQLite database location |

Example `MONITORED_ENDPOINTS`: `api=http://localhost:8000/health, site=https://example.com`

To get a Discord channel id: enable **Developer Mode** (User Settings → Advanced), then
right-click a channel → **Copy ID**. The slash commands register via the application-command
tree; enable the **Message Content Intent** for your bot in the Developer Portal if you use
the @mention/DM conversational path.

## Model requirements

The agentic investigation loop (`/incident`, `/ask`) requires a model that supports
OpenAI-style tool calling. If the configured model does not, the workflow degrades to a
static status+metrics+logs summary. You can verify support by checking whether
`llm_supports_tool_calls()` returns `true` at runtime.

## Conversation memory

The bot keeps a short per-channel conversation history in the same SQLite database
(`conversation_history` table, created lazily on first use). The `/ask` command
and the @mention/DM conversational path all route through `ask_with_memory`, which:

1. fetches the prior turns for the channel as structured `{"role", "content"}` records,
2. stores the user's raw question,
3. runs the agentic loop with those prior turns prepended as real `HumanMessage` /
   `AIMessage` turns (the current question is the final `HumanMessage`, never duplicated
   into the history block), and
4. stores the assistant's answer.

History is **per channel**, not per user, so operators in a shared commands channel share
one conversational context. Each channel retains the 20 most recent turns; the 10 most
recent are folded into the prompt. Tool-call results are not stored — history carries
conversational context only. These limits are module constants in `agent.bot.history`
(`_STORED_LIMIT` and `_HISTORY_LIMIT`); they are not environment-configurable because they
exist only to keep the prompt bounded.

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

# Run automated task evaluation against the live LLM
python -m agent eval                      # all tasks, 1 trial each
python -m agent eval --task api_down
python -m agent eval --trials 5 --label qwen2.5-14b   # pass@k / pass^k
```

See [evals.md](evals.md) for graders, transcripts, and the strength → coverage map.

## Docker

The compose stack (`docker-compose.yml`) runs seven services together:

| Service | Description |
| --- | --- |
| `api` | FastAPI + SQLite on `:8123` (host network) |
| `bot` | Discord bot with background monitor (host network) |
| `web` | React SPA dashboard served via nginx on `:8088` |
| `prometheus` | Metrics store on `:9090` |
| `loki` + `promtail` | Log aggregation on `:3100` (promtail ships n8n + container logs) |
| `n8n` | Workflow automation with built-in `/metrics` on `:5678` |

Build and run all services:

```bash
docker compose up --build
```

Run only one service:

```bash
docker compose up --build api
docker compose up --build bot
```

The `api` and `bot` services mount `./data` so the SQLite database (incidents,
watch list, approvals) persists across restarts. The Docker socket is mounted
read-only for container discovery.
