# Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────────┐
│  Discord    │────▶│   Bot / API  │────▶│  Agent Workflows    │
│  Interface  │     │   Routes     │     │  (incident/report)  │
└─────────────┘     └──────────────┘     └─────────────────────┘
                                                  │
                          ┌───────────────────────┼───────────┐
                          ▼                       ▼           ▼
                   ┌────────────┐         ┌──────────┐   ┌────────┐
                   │   Tools    │         │   LLM    │   │ SQLite │
                   │logs/metrics│         │ (self-   │   │ store  │
                   │ status/src │         │  hosted) │   │        │
                   └────────────┘         └──────────┘   └────────┘
```

## Components

- `agent.bot` — Discord client and chat commands
- `agent.api` — FastAPI server exposing service endpoints
- `agent.workflows` — orchestration for incident investigation and reporting
- `agent.tools` — controlled tools for logs, metrics, and service status
- `agent.tools.sources` — Prometheus and Loki integration stubs
- `agent.llm` — OpenAI-compatible client wrapper for self-hosted models
- `agent.storage` — SQLite repository for incidents
- `agent.alerting` — Discord alert delivery helper
