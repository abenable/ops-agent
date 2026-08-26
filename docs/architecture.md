# Architecture

## The shape of it

```
Discord
  │  slash command, DM, or @mention
  ▼
agent/bot/          slash.py · nl.py · client.py
  │
  ▼
agent/workflows/    investigate.py · report.py
  │  question + thread_id
  ▼
agent/agent.py      ONE create_agent instance ── agent/tools/  (10 read-only tools)
  │                                          └── agent/memory.py (SQLite checkpointer)
  ▼
answer, Discord-formatted
```

Running alongside, unprompted:

```
agent/bot/monitor.py   polls containers + endpoints ──> alerts, event log
agent/bot/digest.py    daily/weekly reports ──────────> #reports
                       status snapshot every 2h ──────> #status-updates
```

## The agent

`src/agent/agent.py` is the whole agent: one `create_agent` call, built once
and cached.

```python
create_agent(
    model=init_chat_model(settings.model_id, timeout=_LLM_TIMEOUT),   # 30s
    tools=[_TOOLS_BY_NAME[t.name] for t in configured_tools()],
    system_prompt=_SYSTEM_PROMPT,            # the Oracle persona
    middleware=[
        ModelRetryMiddleware(max_retries=2),
        ToolCallLimitMiddleware(run_limit=settings.max_tool_steps, exit_behavior="end"),
        ToolRetryMiddleware(max_retries=1),
        ToolErrorMiddleware(aon_error=_tool_error),
        SummarizationMiddleware(model=init_chat_model(...), ...),
    ],
    checkpointer=saver,
)
```

This is the documented LangChain v1 entry point. The tool-calling cycle, the
budget, error recovery, and context compression all come from the framework
rather than from code in this repository.

`get_agent()` caches that instance, keyed on checkpointer identity, and every
workflow shares it. Adding a workflow means writing a new prompt, not building
a second agent.

### The middleware

| Middleware | What it does |
|---|---|
| `ModelRetryMiddleware` | Retries a failed model call up to twice. A run that exhausts the retries ends with `Model call failed`. |
| `ToolCallLimitMiddleware` | Caps a run at `MAX_TOOL_STEPS` **tool calls**. The call that would exceed it is not executed, nor are its siblings on the same message; the run ends with an explanation. |
| `ToolRetryMiddleware` | Retries a raising tool once before the error is handed on. Covers the transient case — a backend that refuses one connection and answers the next. |
| `ToolErrorMiddleware` | A tool still raising after its retry becomes a `ToolMessage` the model can read and react to, instead of an exception that kills the turn. |
| `SummarizationMiddleware` | When the thread passes `MAX_CONTEXT_TOKENS`, older turns are replaced by a summary. That happens in the checkpoint itself, so stored history stays bounded. Runs on `LLM_SUMMARIZER_MODEL` if set. |

### The model

`settings.model_id` is a `provider:model` string, either `openai:...` or
`google_genai:...`, which `init_chat_model` resolves into a client. Building the
client here rather than passing the string to `create_agent` is what makes a
request `timeout` reachable; it is set to 30s for both the answering model and
the summarizer. `temperature` is left at the provider default.

Credentials and endpoint still travel through the environment rather than
through arguments. `settings._export_provider_env()` publishes
`OPENAI_API_BASE`, `OPENAI_API_KEY`, and `GOOGLE_API_KEY` at import, which is
what points a `provider:model` string at a self-hosted endpoint.

Two ceilings sit above the client. `ModelRetryMiddleware` retries a failed call
twice, and `investigate()` wraps the whole run in `asyncio.wait_for` at 60s, so
a provider that hangs past the retries returns `Investigation timed out after
60s` rather than holding the Discord interaction open.

## Memory

`src/agent/memory.py` owns an `AsyncSqliteSaver` on `data/memory.db` and
nothing else opens that file. One connection, so a watch-list write can never
hold a lock the agent is waiting on.

There is one thread per Discord channel or DM, keyed by `thread_id`. Ask a
follow-up in the same channel and the earlier turn is there; ask in another
channel and it is not. Nothing recalls across threads.

Threads survive a bot restart. The saver is opened inside an `AsyncExitStack`
held for the life of the process, and `close_memory()` has to run before the
loop ends, or aiosqlite's worker thread hangs the process at exit. Long threads
stay bounded because `SummarizationMiddleware` compresses them in place.

`thread_config(thread_id)` returns `{"configurable": {"thread_id": ...}}`, which
is the only handle on a conversation. There is deliberately no external API to
read or delete a stored thread.

## Tools

Ten tools, grouped by backend, all read-only. Each carries a description telling
the model when to reach for it and which discovery call to make first.

| Backend | Tools |
|---|---|
| Docker | `list_services`, `docker_status`, `docker_logs` |
| Prometheus | `list_metric_names`, `get_label_values`, `query_prometheus`, `query_prometheus_range` |
| Loki | `get_loki_label_values`, `query_loki`, `query_loki_range` |

Discovery tools exist because the model otherwise invents metric and label
names. `list_services` returns real container names; `list_metric_names` and
`get_label_values` return what Prometheus actually holds;
`get_loki_label_values` returns Loki's labels, which are not Prometheus's.

**Name matching is separator-agnostic** (`agent/normalize.py`): `agent_api`,
`agent-api`, and `AGENT.API` all resolve to `marconi-agent-api`. An exact match
always beats a substring, and an ambiguous partial raises `AmbiguousName` so
the tool reports the candidates rather than guessing.

Range queries and log limits are clamped to `RANGE_MAX_HOURS` and
`LOKI_MAX_LIMIT` so one question cannot pull an unbounded window.

### Read-only by design

No tool mutates anything. There is no restart, stop, scale, or delete, and the
system prompt tells the model to recommend actions for a human operator rather
than claim it can take them. The guarantee is the tool surface, not a
permission flag. `docker.sock` is mounted `:ro` in Compose, but that only makes
the socket *file* read only. The Engine API behind it is still writable, and
socket access is root-equivalent on the host.

## Workflows

Thin wrappers that give the shared agent a question and a thread.

| Module | Entry | Notes |
|---|---|---|
| `workflows/investigate.py` | `investigate(question, thread_id=None)` | Free-form. A stable `thread_id` gives a conversation; omitting it gives a one-shot thread. |
| `workflows/report.py` | `report(service)` | Fills an incident-report template and runs it one-shot. |
| `workflows/nl.py` | `handle_message(bot, message)` | DMs and `@mentions`, keyed to the channel id. Always replies, even on failure. |

## Storage

Two SQLite files under `data/`:

| File | Holds | Opened by |
|---|---|---|
| `agent.db` | `watched_containers`, `events` | `agent/watchlist/repository.py` (sync) |
| `memory.db` | conversation checkpoints | `agent/memory.py` (async, sole connection) |

`DATABASE_URL` points at `agent.db`; `memory.db` is derived to sit beside it.

## Configuration

`agent/config/settings.py` is a pydantic-settings model loaded from the
environment and `.env`. It resolves `DB_PATH`/`MEMORY_DB_PATH` once, relative to
the repo root, so every process agrees on the same files. See
[configuration.md](configuration.md).
