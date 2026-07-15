# Marconi Infrastructure Operations Agent

A minimal MVP of an infrastructure operations agent with a Discord interface, backend API, self-hosted LLM integration, and incident workflows.

## Quick start

```bash
uv sync
cp .env.example .env
# edit .env with your Discord token and LLM endpoint
python -m agent bot
```

## Project structure

```
.
├── main.py                  # Backwards-compatible launcher
├── src/agent/               # Core package
│   ├── bot/                 # Discord interface and commands
│   ├── api/                 # FastAPI backend service
│   ├── llm/                 # Self-hosted LLM client
│   ├── tools/               # Agent tools
│   │   ├── sources/         # Prometheus, Loki integrations
│   │   ├── health.py        # HTTP endpoint checks
│   │   ├── incidents.py     # Incident ack/resolve/list
│   │   ├── docker.py        # Docker list/logs/restart
│   │   └── ssh.py           # Remote SSH commands / restarts
│   ├── workflows/           # Incident investigation & reporting
│   ├── storage/             # SQLite incident storage
│   ├── alerting/            # Discord alert delivery
│   └── config/              # Environment-based settings
├── tests/                   # Test suite
├── scenarios/               # Simulated infrastructure issues
├── docs/                    # Setup, usage, architecture, workflows
└── data/                    # SQLite database
```

## Documentation

- [Setup](docs/setup.md)
- [Usage](docs/usage.md)
- [Architecture](docs/architecture.md)
- [Workflows](docs/workflows.md)

## What is included

- Discord bot interface and command handling
- FastAPI backend service and routes
- Controlled agent tools for logs, metrics, service status, HTTP health, Docker, and SSH
- Incident action tools (acknowledge, resolve, list)
- Prometheus and Loki integration stubs
- Self-hosted LLM integration via OpenAI-compatible endpoints
- Incident investigation and reporting workflows
- SQLite storage for incidents
- Discord alert delivery helper
- Test scaffolding and simulated scenario files

## What is still stubbed

- Real monitoring source authentication and queries
- Actual log/metric/service collectors
- Rich workflow state machines (LangGraph can be added later)
- Alert routing rules and escalation

See the `// ponytail:` comments for deliberate shortcuts and how to extend them.
