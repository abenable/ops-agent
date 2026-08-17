# Setup

## Prerequisites

- Docker + Docker Compose (the agent inspects containers via the Docker socket)
- A Discord application/bot — <https://discord.com/developers/applications>
- A self-hosted, OpenAI-compatible LLM endpoint with **tool-calling support**
  (Ollama, vLLM, llama.cpp server, or a gateway in front of them)
- Python 3.13+ with [uv](https://docs.astral.sh/uv/) for local runs

## Discord bot

1. Create an application → Bot → copy the token.
2. Enable the **Message Content Intent** (Bot page → Privileged Gateway
   Intents). Without it the bot cannot read @mentions/DMs and exits with a
   clear error.
3. Invite the bot with the `bot` + `applications.commands` scopes and
   Send Messages / Embed Links / Read Message History permissions.

## Configuration

```bash
cp .env.example .env
```

Minimum required:

| Variable | Purpose |
| --- | --- |
| `DISCORD_BOT_TOKEN` | Bot token from the developer portal |
| `LLM_BASE_URL` / `LLM_MODEL` | OpenAI-compatible endpoint and model name |

Optional but recommended:

| Variable | Purpose |
| --- | --- |
| `DISCORD_GUILD_ID` | Guild-scoped slash-command sync (faster while testing) |
| `DISCORD_ALERT_CHANNEL_ID` | Where container-down and endpoint-down alerts land |
| `DISCORD_STATUS_CHANNEL_ID` | Container and endpoint recovery notes |
| `DISCORD_LOG_CHANNEL_ID` | The bot's own INFO+ log stream |
| `DOCKER_MONITOR` | `true` to enable the container poll (endpoint polling is always on when `MONITORED_ENDPOINTS` is set) |
| `MONITORED_ENDPOINTS` | Comma-separated `name=url` pairs polled by the monitor for down/recovery alerts |

See `.env.example` for the full list with comments. Every field maps to a
setting in `src/agent/config/settings.py`.

## Run

With Docker Compose (bot + Prometheus + Loki + Promtail + node-exporter +
cAdvisor):

```bash
docker compose up --build
```

Or locally (bot only; Prometheus/Loki URLs still come from `.env`):

```bash
uv sync
python -m agent bot
```

A successful start logs `Bot logged in as ...` and `Synced N slash command(s)`.
