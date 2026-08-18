# Marconi Infrastructure Operations Agent

A Discord bot that answers infrastructure questions about a small self-hosted lab.
Ask it something in a channel, a DM, or through a slash command, and it runs an LLM
tool-calling loop over the Docker Engine API, Prometheus and Loki, gathers evidence,
and replies with what it found plus a likely cause and next steps. Every tool it has
is read-only, so it reports and recommends but never restarts, scales, or edits
anything. Alongside the conversational side it polls containers and HTTP endpoints in
the background, alerts on state changes, and posts scheduled daily and weekly digests.

## Features

- Natural-language investigation over 10 read-only tools (container state and logs,
  PromQL instant and range queries, LogQL instant and range queries, metric and label
  discovery).
- Per-channel conversation memory, checkpointed to SQLite, so follow-up questions keep
  context across bot restarts.
- 11 slash commands for status, investigation, incident reports, digests, and the
  container watch list.
- Background monitor: container stop/start transitions read straight from the Docker
  socket, plus HTTP endpoint probes, both alerting to Discord channels.
- Daily and weekly digests where the numbers come from the recorded event table and
  only the summary prose comes from the model.
- Separator-agnostic name matching, so `agent_api` resolves `marconi-agent-api`, and an
  ambiguous partial name is reported instead of guessed.
- Works with any OpenAI-compatible chat endpoint (Ollama, vLLM, llama.cpp server, a
  LiteLLM proxy).

## Requirements

- Python 3.13 or newer, and [uv](https://docs.astral.sh/uv/).
- A Discord application with a bot token and the privileged Message Content Intent
  enabled (the bot exits with an explanatory log line if it is not).
- An OpenAI-compatible chat completions endpoint.
- Optional but expected in normal use: a readable Docker socket, a Prometheus server,
  and a Loki server.

## Quick start

```bash
uv sync
cp .env.example .env
# Edit .env: set DISCORD_BOT_TOKEN, LLM_BASE_URL, LLM_MODEL (LLM_API_KEY if your
# endpoint requires one).
uv run python -m agent bot
```

`uv sync` installs the project, so `uv run agent bot` works as well (`agent` is the
console script declared in `pyproject.toml`).

With Docker Compose, which also brings up Prometheus, Loki and Promtail:

```bash
cp .env.example .env   # same edits as above
docker compose up -d --build
docker compose logs -f bot
```

The `bot` service runs with `network_mode: host`, mounts `./data` for the SQLite file
and mounts `/var/run/docker.sock` so the Docker tools can see host containers. See
`docs/deployment.md` for the details and the security note about the socket mount.

## Discord commands

| Command | What it does |
| --- | --- |
| `/status` | Summarize container health and configured endpoints. |
| `/investigate <question>` | Free-form investigation, keeps this channel's context. |
| `/report <service>` | Structured incident report for one service. |
| `/digest [period] [post_to_reports]` | Render the daily or weekly report now. |
| `/containers` | List Docker containers grouped by status. |
| `/watching` | List the HTTP endpoints the monitor polls. |
| `/watch <container>` | Add a container to the watch list. |
| `/unwatch <container>` | Remove a container from the watch list. |
| `/watchlist` | List the watched containers. |
| `/reset` | Clear this channel's conversation history. |
| `/help` | List what the agent can do. |

DMs and `@mentions` go through the same loop as `/investigate`. See `docs/usage.md`.

## Project layout

```
src/agent/
├── cli.py             # argparse entry point: `agent bot` / `python -m agent bot`
├── engine.py          # generic LangGraph tool-calling loop (model node, tools node)
├── memory.py          # SQLite checkpointer, thread config, context trimming
├── normalize.py       # separator-agnostic name matching, one resolution rule
├── config/settings.py # pydantic-settings Settings singleton, .env loading, DB_PATH
├── llm/client.py      # get_llm(): ChatOpenAI against an OpenAI-compatible base URL
├── tools/             # the read-only tool surface (ALL_TOOLS)
│   ├── docker.py      # Engine API client + list_services, docker_status, docker_logs
│   ├── prometheus.py  # instant/range PromQL, metric names, label values
│   └── loki.py        # instant/range LogQL, label values
├── workflows/         # units of work, each a plain `async def -> str`
│   ├── investigate.py # the Oracle prompt bound to every tool
│   ├── report.py      # the same loop with a fixed incident-report template
│   └── nl.py          # DM and @mention handling
├── watchlist/         # sqlite3 repository: watched containers, transition events
├── alerting/discord.py# embed alerts and multi-chunk report posting
└── bot/               # the Discord layer
    ├── client.py      # run_bot(), intents, on_ready wiring, log forwarding
    ├── slash.py       # the 11 slash commands and the tree error handler
    ├── monitor.py     # container and endpoint polling loop
    ├── digest.py      # scheduled daily and weekly reports
    ├── summarize.py   # LLM cleanup of raw output, Discord markdown fixes
    └── utils.py       # container list formatting, message chunking
```

## Tests

```bash
uv run pytest              # the default run: fully offline
uv run pytest -m integration   # live checks against Discord and the LLM endpoint
```

The default run needs no network, no Docker, no Discord and no LLM. See
`docs/development.md`.

## Documentation

Full documentation lives in [`docs/`](docs/README.md).

- [Architecture](docs/architecture.md): how the layers fit together.
- [Agent loop](docs/agent-loop.md): the engine, memory, and the tool budget.
- [Tools](docs/tools.md): each tool, its arguments, and its limits.
- [Monitoring](docs/monitoring.md): the background monitor, alerts, and digests.
- [Configuration](docs/configuration.md): every environment variable.
- [Deployment](docs/deployment.md): Docker Compose and the stack it brings up.
- [Usage](docs/usage.md): talking to the bot in Discord.
- [Development](docs/development.md): extending the project.
- [Evaluation](docs/evaluation.md): the notebook harness for model behaviour.

[`docs/pdf/report.pdf`](docs/pdf/report.pdf) is a standalone report on the design and
implementation, written to be readable without access to this repository.
