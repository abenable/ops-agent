# Setup

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- A Discord bot token and a server to test in
- A self-hosted LLM exposing an OpenAI-compatible chat endpoint (e.g. Ollama)

## Installation

```bash
uv sync
```

For development dependencies:

```bash
uv sync --dev
```

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Key variables:

- `DISCORD_BOT_TOKEN` — required to run the bot
- `LLM_BASE_URL` / `LLM_MODEL` — point at your local LLM
- `DATABASE_URL` — defaults to `sqlite:///data/agent.db`

## Run

```bash
# Discord bot
python -m agent bot

# HTTP API
python -m agent api

# One-shot incident workflow
python -m agent incident --service web
```

## Docker

Build and run both services:

```bash
docker compose up --build
```

Run only the API:

```bash
docker compose up --build api
```

Run only the Discord bot:

```bash
docker compose up --build bot
```

The `api` service exposes port `8000` and the `bot` service waits until the API healthcheck passes.

