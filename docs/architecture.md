# Architecture

```
   Discord users                              HTTP clients
        │                                          │
        ▼                                          ▼
┌───────────────┐   ┌──────────────┐      ┌──────────────────┐
│  Bot commands │   │   Monitor    │      │   FastAPI routes │
│  (!status …)  │   │  (poll loop) │      │  (+ API key dep) │
└───────┬───────┘   └──────┬───────┘      └────────┬─────────┘
        │                  │                       │
        └──────────────────┼───────────────────────┘
                           ▼
                ┌─────────────────────┐
                │   Agent workflows   │
                │ (incident / report) │
                └──────────┬──────────┘
             ┌─────────────┼──────────────┬───────────────┐
             ▼             ▼              ▼               ▼
      ┌────────────┐ ┌──────────┐  ┌──────────┐   ┌──────────────┐
      │   Tools    │ │   LLM    │  │  SQLite  │   │  Alerting /  │
      │ status/logs│ │ (OpenAI- │  │  store   │   │  Discord     │
      │metrics/http│ │ compat.) │  │incidents │   │ channels     │
      │docker/ssh  │ └──────────┘  └──────────┘   └──────────────┘
      └─────┬──────┘
            ▼
    ┌────────────────┐
    │ Prometheus /   │
    │ Loki sources   │
    └────────────────┘
```

## Components

- `agent.bot.client` — Discord client bootstrap; on ready it starts the monitor and, if
  configured, a Discord log handler.
- `agent.bot.commands` — prefix command handlers.
- `agent.bot.monitor` — background poll loop over `MONITORED_ENDPOINTS`; drives alerts, status
  updates, and escalation to threaded incidents.
- `agent.api` — FastAPI app and routes, with an optional `X-API-Key` dependency.
- `agent.workflows` — incident investigation and report generation.
- `agent.tools` — controlled tools: status, logs, metrics, HTTP health, Docker, SSH.
- `agent.tools.sources` — Prometheus (metrics) and Loki (logs) query helpers.
- `agent.llm` — OpenAI-compatible client wrapper (`ChatOpenAI`) for a self-hosted model.
- `agent.storage` — SQLite repository and the `Incident` dataclass.
- `agent.alerting` — Discord alert embeds and incident-thread creation.
- `agent.config` — Pydantic settings loaded from environment and `.env`.

## Data flow (incident)

1. A trigger arrives — `!incident <service>`, `POST /incidents/{service}`, the CLI, or the
   monitor escalating a down endpoint.
2. The workflow gathers status + metrics + logs via the tools (which query Prometheus/Loki,
   falling back to stubs on failure).
3. The context is sent to the LLM for a one-paragraph summary (with a graceful fallback if the
   LLM is offline).
4. The incident is persisted to SQLite and its id returned.
5. For Discord triggers, a thread is opened in the incidents channel and an alert is posted.

## Storage schema

Single `incidents` table:

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT PK | 8-char short uuid |
| `service` | TEXT | service / endpoint name |
| `summary` | TEXT | LLM (or fallback) summary |
| `status` | TEXT | `open` / `acknowledged` / `resolved` |
| `thread_id` | INTEGER | Discord thread id, if one was opened |
| `created_at` | TEXT | ISO timestamp |

The database path is resolved relative to the repository root, so every entry point (bot, API,
CLI, tests) shares one database.
