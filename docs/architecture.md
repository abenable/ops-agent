# Architecture

```
   Discord users                              HTTP clients
        │                                          │
        ▼                                          ▼
┌───────────────┐   ┌──────────────┐      ┌──────────────────┐
│ Bot commands  │   │   Monitor    │      │   FastAPI routes │
│(!/ / status…) │   │  (poll loop) │      │  (+ API key dep) │
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
      │status/logs │ │ (OpenAI- │  │  store   │   │  Discord     │
      │metrics/http│ │ compat.) │  │incidents │   │ channels     │
      │docker/ssh  │ └──────────┘  └──────────┘   └──────────────┘
      │+ discovery │
      └─────┬──────┘
            ▼
    ┌────────────────┐
    │ Prometheus /   │
    │ Loki sources   │
    └────────────────┘
```

## Components

- `agent.bot.client` — Discord client bootstrap; on ready it starts the monitor, syncs the
  slash-command tree, and, if configured, a Discord log handler.
- `agent.bot.commands` — prefix (`!`) command handlers.
- `agent.bot.slash` — slash (`/`) command handlers via the `CommandTree`.
- `agent.bot.menu` — interactive container picker and action buttons.
- `agent.bot.views` — service panel view and persistent incident action buttons.
- `agent.bot.summarize` — LLM reply summarisation of verbose output, with a `raw` opt-out.
- `agent.bot.monitor` — background poll loop; each cycle checks HTTP endpoint liveness
  (`MONITORED_ENDPOINTS`) and evaluates PromQL alert rules (`PROMETHEUS_ALERT_RULES`), driving
  alerts, status updates, and escalation to threaded incidents.
- `agent.api` — FastAPI app and routes, with an optional `X-API-Key` dependency.
- `agent.workflows` — incident investigation (agentic tool-calling loop) and report generation.
- `agent.tools` — controlled tools: status, logs, metrics, HTTP health, Docker, SSH.
- `agent.tools.normalize` — separator-agnostic service-name matching.
- `agent.tools.sources` — Prometheus (metrics) and Loki (logs) query helpers.
- `agent.tools.query_tools` — read-only LangChain tools the LLM calls during an investigation:
  service discovery (`list_services`), Prometheus/Loki metric/label discovery and queries, and
  read-only Docker container status/logs.
- `agent.llm` — OpenAI-compatible client wrapper (`ChatOpenAI`) for a self-hosted model.
- `agent.storage` — SQLite repository and the `Incident` dataclass.
- `agent.alerting` — Discord alert embeds and incident-thread creation.
- `agent.config` — Pydantic settings loaded from environment and `.env`.

## Data flow (incident)

1. A trigger arrives — `!incident <service>` / `/incident`, `POST /incidents/{service}`, the
   CLI, or the monitor escalating a down endpoint / firing PromQL rule.
2. The workflow runs a bounded agentic loop: the LLM calls `list_services` to learn the real
   names, discovers metrics/labels, writes its own PromQL/LogQL through the read-only query
   tools, and can inspect containers with `docker_status`/`docker_logs`, up to `MAX_TOOL_STEPS`
   calls.
3. The model returns a summary. If it does not support tool calls, fails, or produces nothing,
   the workflow falls back to a static status+metrics+logs summary (which itself falls back to
   raw context if the LLM is offline).
4. The incident is persisted to SQLite and its id returned.
5. For Discord triggers, a thread is opened in the incidents channel with persistent
   Acknowledge/Resolve buttons, and an alert is posted.

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
