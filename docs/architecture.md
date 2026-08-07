# Architecture

```
   Discord users                              HTTP clients
        │                                          │
        ▼                                          ▼
┌───────────────┐   ┌──────────────┐      ┌──────────────────┐
│ Bot commands  │   │   Monitor    │      │   FastAPI routes │
│(/ status…)    │   │  (poll loop) │      │  (+ API key dep) │
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
- `agent.bot.slash` — slash (`/`) command handlers via the `CommandTree`.
- `agent.bot.menu` — interactive container picker and action buttons.
- `agent.bot.views` — service panel view and persistent incident action buttons.
- `agent.bot.summarize` — LLM reply summarisation of verbose output, with a `raw` opt-out.
- `agent.bot.history` — per-channel conversational memory. The `conversation_history` SQLite
  table stores the last 20 turns per channel; the 10 most recent are passed as structured
  `HumanMessage`/`AIMessage` turns into the agentic loop so the agent resolves vague references
  (`logs`, `the web container`, `that one`) from prior context. `ask_with_memory` wraps the
  fetch-record-run-store cycle for the @mention and `/ask` paths.
- `agent.bot.monitor` — background poll loop; each cycle checks HTTP endpoint liveness
  (`MONITORED_ENDPOINTS`) and inspects Docker containers when `DOCKER_MONITOR` is
  enabled, alerting on a running→stopped transition (Docker-only alerting —
  Prometheus is kept for metrics, not alerting) — driving alerts, status updates,
  and escalation to threaded incidents.
- `agent.api` — FastAPI app and routes, with an optional `X-API-Key` dependency.
  Exposes `GET /metrics` (Prometheus self-metrics) and SSE streaming for the agentic loop.
- `agent.workflows` — incident investigation (agentic tool-calling loop), remediation
  (proposes restarts behind human approval), and report generation.
- `agent.tools` — controlled tools: status, logs, metrics, HTTP health, Docker, SSH.
- `agent.tools.normalize` — separator-agnostic service-name matching.
- `agent.tools.sources` — Prometheus (metrics) and Loki (logs) query helpers.
- `agent.tools.query_tools` — read-only LangChain tools the LLM calls during an investigation:
  service discovery (`list_services`), Prometheus/Loki metric/label discovery and queries, and
  read-only Docker container status/logs.
- `agent.eval` — task evaluation harness; loads YAML tasks, runs N trials per task,
  grades each trial with multiple code-based graders (tool_calls, no_raw_markup,
  groundedness, no_false_alarm), and aggregates pass@k / pass^k. See [evals.md](evals.md).
- `agent.metrics` — Prometheus counters and histograms for the agent itself (tool calls,
  investigations, LLM calls, monitor cycles, alerts, API requests).
- `agent.llm` — OpenAI-compatible client wrapper (`ChatOpenAI`) for a self-hosted model.
- `agent.storage` — SQLite repository for incidents, watched containers, and remediation
  pending-approvals.
- `agent.alerting` — Discord alert embeds and incident-thread creation.
- `agent.config` — Pydantic settings loaded from environment and `.env`.

## Data flow (incident)

1. A trigger arrives — `/incident <service>`, `POST /incidents/{service}`, the
   CLI, or the monitor escalating a down endpoint / stopped container.
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

`incidents` table:

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT PK | 8-char short uuid |
| `service` | TEXT | service / endpoint name |
| `summary` | TEXT | LLM (or fallback) summary |
| `status` | TEXT | `open` / `acknowledged` / `resolved` |
| `thread_id` | INTEGER | Discord thread id, if one was opened |
| `created_at` | TEXT | ISO timestamp |

`watched_containers` table:

| Column | Type | Notes |
| --- | --- | --- |
| `name` | TEXT PK | exact container name |
| `created_at` | TEXT | ISO timestamp |

`pending_approvals` table:

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT PK | 8-char short uuid |
| `incident_id` | TEXT FK | parent incident |
| `container_name` | TEXT | target container |
| `container_id` | TEXT | Docker container id (optional) |
| `action` | TEXT | proposed action (e.g. `restart`) |
| `status` | TEXT | `pending` / `running` / `approved` / `rejected` / `expired` / `failed` |
| `created_at` | TEXT | ISO timestamp |

A pending approval transitions to `running` via an atomic conditional UPDATE
(`claim_pending_approval`) when a human approves, so a concurrent approval
(button + `/approve`, or a double-click) cannot double-execute the restart —
only the first caller wins the row. On restart success it becomes `approved`;
on restart error, `failed`.

`conversation_history` table (created lazily by `agent.bot.history`):

| Column | Type | Notes |
| --- | --- | --- |
| `id` | INTEGER PK | autoincrement |
| `channel_id` | INTEGER | Discord channel id (history is per-channel) |
| `role` | TEXT | `user` or `assistant` |
| `content` | TEXT | trimmed to 4,000 chars; tool outputs are not stored |
| `created_at` | TEXT | ISO timestamp, indexed with `channel_id` |

The table is scoped **per channel**, not per user, so operators in a shared commands channel
see one shared conversational context. Each channel keeps the 20 most recent turns; the 10
most recent are passed as structured message turns into the agentic loop. Tool-call results
are not stored — history carries conversational context only.

The database path is resolved relative to the repository root, so every entry point (bot, API,
CLI, tests) shares one database.
