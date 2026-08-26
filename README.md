# Marconi Infrastructure Operations Agent

A Discord bot that answers questions about the Marconi lab's Docker services by
actually looking. It reads container state, logs, and metrics with read-only
tools, then says what it found.

Ask it `why is loki down?` in a channel and it will check the container, read
the logs, query Prometheus, and answer with evidence. It also watches the
services on its own and posts an alert when one stops.

```
you   > @oracle why did the api container restart?
oracle> tool call: list_services()
        tool call: docker_status(container="marconi-agent-api")
        tool call: query_loki_range(logql='{container="marconi-agent-api"}', minutes=30)

        **What happened** — `marconi-agent-api` restarted 12 minutes ago...
        **Likely cause** — OOM: the log shows `MemoryError` immediately before exit.
        **Next steps** — raise the container memory limit, or cap the batch size.
```

## Quick start

```bash
cp .env.example .env      # set DISCORD_BOT_TOKEN and your LLM provider
docker compose up -d      # the bot
```

Or without Docker:

```bash
uv sync
uv run agent bot
```

Compose builds and runs the bot only. Point `PROMETHEUS_URL` and `LOKI_URL` at
your existing metrics and log servers; with either unset, those tools are simply
unavailable.

## What it can do

DM it or `@mention` it in a channel and ask in plain English. It remembers the
conversation per channel, so follow-ups work.

The same thing is available as slash commands:

| Command | Does |
|---|---|
| `/investigate <question>` | Free-form investigation |
| `/status` | Container and endpoint health right now |
| `/report <service>` | A structured incident report for one service |
| `/digest [daily\|weekly]` | Render the scheduled infrastructure report on demand |
| `/containers`, `/watching`, `/watchlist` | List what exists and what is being watched |
| `/watch`, `/unwatch` | Manage the container watch list |
| `/help` | The above, in Discord |

It also runs unprompted: a background monitor alerts when a watched container
stops or an endpoint stops answering, a status snapshot posts every two hours,
and a scheduled digest posts daily and weekly summaries.

## Read-only by design

Every tool the model can call is a read. Nothing restarts, scales, or deletes
anything. The agent recommends actions for a human operator and cannot carry
them out. See [docs/architecture.md](docs/architecture.md#read-only-by-design).

## Documentation

| Guide | What's in it |
|---|---|
| [architecture.md](docs/architecture.md) | How the pieces fit: the agent, its memory, its tools |
| [configuration.md](docs/configuration.md) | Every environment variable |
| [deployment.md](docs/deployment.md) | Docker Compose, the image, backups |
| [usage.md](docs/usage.md) | Commands and how to talk to it |
| [monitoring.md](docs/monitoring.md) | Alerts, the watch list, scheduled digests |
| [development.md](docs/development.md) | Layout, tests, conventions |
| [evaluation.md](docs/evaluation.md) | The eval notebooks and transcript harness |

## Requirements

Python 3.13+, a Discord bot token, and an LLM. The LLM can be a self-hosted
OpenAI-compatible endpoint (Ollama, vLLM, llama.cpp) or a Google Gemini API
key. The container tools need Docker access. Prometheus and Loki are optional;
with their URLs unset, those tools simply become unavailable.
