# Marconi Infrastructure Operations Agent

An MVP infrastructure-operations agent that lives in Discord. It answers operator
questions about lab services (status, logs, metrics) through an agentic
tool-calling loop, summarizes infrastructure health, generates structured
incident reports, and raises container down/recovery alerts — all powered by a
self-hosted, OpenAI-compatible LLM and read-only tools.

Built during the Implementation Phase (Weeks 5–8) of the Marconi industrial training.

## Features

- **Agentic investigation** — `/investigate <question>` (or @mention/DM the bot):
  the LLM discovers real service names, writes its own PromQL/LogQL through
  read-only Prometheus and Loki tools, and inspects containers with read-only
  Docker status/logs tools, in a bounded tool-calling loop. Service names match
  separator-agnostically (`agent_api` finds `marconi-agent-api`).
- **Health status** — `/status` summarizes container states and monitored
  endpoints, cleaned up by the LLM for a readable answer.
- **Incident reports** — `/report <service>` runs the same loop with a fixed
  incident template: Summary → What happened → Evidence → Likely cause →
  Recommended next steps.
- **Background alerts** — a monitor loop polls containers and posts a critical
  alert when a tracked container stops, and a recovery note when it comes back.
  Containers are tracked when they match `DOCKER_NAME_FILTER` or are explicitly
  watched via `/watch`.
- **Self-hosted LLM** — points at any OpenAI-compatible endpoint (Ollama, vLLM,
  llama.cpp server, a hosted gateway). Tool-calling support required for
  investigations.

Safety boundary: every tool the LLM can call is **read-only**. It cannot
restart containers or change configuration; it can only recommend actions for a
human operator.

## Quick start

```bash
uv sync
cp .env.example .env
# edit .env: at minimum set DISCORD_BOT_TOKEN and your LLM endpoint
python -m agent bot        # run the Discord bot
```

## Discord commands

| Command | Description |
| --- | --- |
| `/status` | LLM-cleaned summary of container + endpoint health |
| `/investigate <question>` | Free-form agentic investigation using read-only tools |
| `/report <service>` | Structured incident report for one service |
| `/containers [raw]` | List Docker containers grouped by state |
| `/watching` | List endpoints configured for background monitoring |
| `/watch <container>` | Add a container to the watch list (status updates + down-alerts) |
| `/unwatch <container>` | Remove a container from the watch list |
| `/watchlist` | List the containers currently being watched |
| `/project-notes` | Post/refresh the project-notes embed |
| `/info` | Bot info and support links |

You can also **@mention** or DM the bot with a question; it answers through the
same agentic loop as `/investigate`.

## Discord channels

The bot maps its output to purpose-specific channels (all optional; a feature is
simply inactive when its channel id is unset).

| Channel | Role |
| --- | --- |
| `#alerts` | Container down-alerts (critical embeds) |
| `#status-updates` | Recovery notes and periodic status snapshots |
| `#agent-logs` | The bot's own INFO+ log stream (optional) |
| `#welcome` / `#project-notes` | Onboarding embeds, refreshed in place on startup |

## Project structure

```
.
├── src/agent/
│   ├── bot/                 # Discord client, slash commands, monitor loop, onboarding, summarize
│   ├── tools/               # Docker/Prometheus/Loki clients + read-only LangChain tools
│   ├── investigate.py       # The agentic tool-calling loop (/investigate, /report, mentions)
│   ├── normalize.py         # Separator-agnostic service-name matching
│   ├── llm/                 # Self-hosted LLM client (OpenAI-compatible)
│   ├── memory/              # SQLite repository for the container watch list
│   ├── alerting/            # Discord alert embeds
│   └── config/              # Environment-based settings
├── tests/                   # Test suite
└── data/                    # SQLite database
```

## Testing

```bash
uv run pytest                  # unit + smoke tests (no external services needed)
uv run pytest -m integration   # live checks (needs a real LLM / Discord token)
```

## Documentation

- [Architecture](docs/architecture.md) — components, data flow, safety boundaries

## Limitations

This is an MVP built for a controlled environment. Known limitations:

- **Investigations need a tool-calling model** — if the configured LLM does not
  support OpenAI-style tool calls, `/investigate` and `/report` cannot reason
  over tools and will mostly echo the prompt back.
- **Alerting is Docker-only** — a container stopping is observed from the Docker
  socket; there is no PromQL alert-rule evaluation.
- **Monitor state is in memory** — alert de-duplication resets when the bot
  restarts (the first poll after a restart baselines state without alerting, so
  a restart never produces a false alarm).
- **No RBAC** — any member who can see the bot's channel can run any command.
  All LLM-reachable tools are read-only by construction.
- **Single-node SQLite** — stores the watched-container list; fine for one bot
  instance.

## Future improvements

- Human-approved remediation actions (e.g. restart a container after an
  operator clicks Approve) — the safety boundary for this already exists: the
  LLM never gets a mutating tool.
- PromQL alert-rule evaluation in the monitor loop alongside Docker polling.
- Persist monitor/alert state so de-duplication survives restarts.
- An eval harness that replays simulated incidents against the investigation
  loop and grades tool selection and summary grounding.
