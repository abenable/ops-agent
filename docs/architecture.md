# Architecture

## What this is

Marconi is a read-only infrastructure operations agent for a small self-hosted lab,
driven entirely from Discord. It answers ops questions in natural language by running
an LLM tool-calling loop over three backends (the Docker Engine API, Prometheus, Loki),
watches containers and HTTP endpoints in the background, alerts on state transitions,
and posts scheduled daily and weekly digests.

The problem it solves: answering "why did the api container restart?" normally means
opening three UIs and correlating them by hand. The agent does the fetching and the
correlating. It cannot act on what it finds. Nothing in `src/agent/tools/` issues a
mutating call, so the worst outcome of a bad model turn is a wrong answer, not a
stopped container.

Python 3.13+, distributed as the package `agent`. One entry point:

```bash
agent bot          # or: python -m agent bot
```

`src/agent/cli.py` parses a single subcommand and calls `run_bot()`. Everything else
runs inside the discord.py event loop.

## Layer map

Imports run downward. Nothing below the bot layer imports discord.py except
`src/agent/alerting/discord.py` and `src/agent/workflows/nl.py`.

```text
  cli.py
    |
    v
  bot/            client.py  slash.py  monitor.py  digest.py  summarize.py  utils.py
    |   \
    |    \--------------> alerting/discord.py
    v
  workflows/      investigate.py  report.py  nl.py
    |
    v
  engine.py --------------> memory.py
    |
    v
  tools/          docker.py  prometheus.py  loki.py
    |
    v
  llm/client.py

  used from several levels:  config/settings.py   normalize.py   watchlist/repository.py
```

### config (`src/agent/config/settings.py`)

A pydantic-settings `Settings` singleton plus `DB_PATH`. `.env` is located with
`find_dotenv()` and loaded without overriding real environment variables.
`env_parse_none_str=""` turns a blank env var into `None`, which is what the optional
`int | None` channel ids need; a `model_validator(mode="before")` puts plain `str`
fields back to `""` so a blank `DOCKER_NAME_FILTER=` does not become `None`.
`DB_PATH` is resolved once from `DATABASE_URL`, made absolute against the repo root,
and its parent directory is created at import time.

Knows nothing about what any setting is for.

### llm (`src/agent/llm/client.py`)

`get_llm(temperature=0.0)` returns a `ChatOpenAI` pointed at `LLM_BASE_URL` with a 60
second timeout. Any OpenAI-compatible server works: Ollama, vLLM, llama.cpp, a LiteLLM
proxy. No tools are bound here and no prompt is attached; that is the caller's job.

### engine (`src/agent/engine.py`)

The tool-calling loop, and the only piece of real control flow in the project. It is
generic: it never imports `agent.tools`, never hardcodes a persona, and has no Discord
types anywhere. Callers hand it a `tools_by_name` dict, a system prompt, a budget
prompt and an optional thread id. See `docs/agent-loop.md` for the walkthrough.

Does not know: which tools exist, what Docker or Prometheus or Loki are, what a Discord
channel is, or what an error should look like to a user.

### memory (`src/agent/memory.py`)

Conversation state: the LangGraph checkpointer, thread configuration, and the context
window trimmer. Keyed by `thread_id`, which is a string as far as this module is
concerned. Also covered in `docs/agent-loop.md`.

Does not know: that a thread id is usually a Discord channel id, or what is in the
messages it trims.

### normalize (`src/agent/normalize.py`)

Separator-agnostic name matching, with no I/O at all. `normalize()` strips `[-_\s.]`
and lowercases, so `agent_api`, `agent-api` and `agentapi` are the same name.
`resolve_one()` is the single matching rule used by every container, service and
watch-list lookup:

```python
matches = [c for c in candidates if needle in normalize(key(c))]   # substring match
# an exact normalized match always wins over a substring match
# more than one substring match raises AmbiguousName
```

`AmbiguousName` is a `LookupError` carrying the candidate list, so callers can render
"use one of these exact names" instead of guessing.

### tools (`src/agent/tools/`)

Ten LangChain `@tool` functions in `ALL_TOOLS`, grouped by backend. Each module is a
thin async client half (httpx2) and a `@tool` half. Every tool returns a string,
truncated to 4000 characters.

- `docker.py`: speaks Docker Engine API v1.40 directly over httpx2, either through a
  Unix socket (`AsyncHTTPTransport(uds=...)` with a `http://localhost` base URL) or a
  `tcp://` host. `_docker_host()` reads `os.environ.get("DOCKER_HOST") or <default>`
  rather than passing a default to `get()`, because compose files and `.env` commonly
  set `DOCKER_HOST=` empty and an empty string would reach the transport.
  `list_containers()` returns `[]` when Docker is unreachable rather than raising.
  `_demux_docker_stream()` strips Docker's 8-byte log framing (1 byte stream type, 3
  reserved, 4-byte big-endian length) that non-tty containers get.
  Tools: `list_services`, `docker_status`, `docker_logs` (tail clamped to 200).
- `prometheus.py`: `query_prometheus`, `list_metric_names` (capped at 500),
  `get_label_values`, `query_prometheus_range` (window clamped to `RANGE_MAX_HOURS`,
  step `max(15, minutes * 60 // 100)`).
- `loki.py`: `get_loki_label_values`, `query_loki`, `query_loki_range` (limit clamped
  to `LOKI_MAX_LIMIT`). `query()` does not use Loki's instant `/query` endpoint, which
  rejects plain log-stream selectors ("log queries are not supported as an instant
  query type"); it delegates to a 15 minute range query instead.

Both metric backends validate label names against `^[A-Za-z_][A-Za-z0-9_]*$` before
interpolating them into a URL path, which rejects `/`, `?`, `#`, `..` and whitespace.
A bearer token header is added only when the matching token setting is non-empty.

Tools do not know they are being called by an agent, and they never raise past the
engine on purpose; the engine catches whatever they throw.

### workflows (`src/agent/workflows/`)

The units of work a command triggers.

- `investigate.py`: the Oracle system prompt plus all ten tools, run through
  `engine.run`. The prompt tells the model to call `list_services` when unsure of a
  name, to prefer evidence over guessing (state, then logs, then metrics), to recommend
  actions for a human rather than claiming to act, to answer in Discord markdown with
  no `#` headings and no tables, and to end with a likely cause and next steps. Every
  exception is caught and returned as `"Investigation failed: ..."`. The answer is
  passed through `discordify`.
- `report.py`: the same loop with a fixed template producing Summary / What happened /
  Evidence / Likely cause / Recommended next steps. Always one-shot, no thread id.
- `nl.py`: the adapter for DMs and @mentions. It is the one workflow with Discord types
  in its signature (`handle_message(bot, message)`), because it is handling a message
  event rather than answering a question. It ignores its own and other bots' messages,
  answers in a guild only when mentioned, strips the mention markup, and uses
  `thread_id = str(message.channel.id)` so a channel or DM keeps context. It lives here
  rather than as a closure in `bot/client.py` so it can be tested and, more importantly,
  so it can be wrapped in a try/except that always replies: an exception raised inside a
  discord.py event handler is logged to the `discord.client` logger, which this bot's own
  Discord log handler deliberately filters out, so a failure there looks like silence.

`investigate()` and `report()` take and return strings. They do not know whether the
result is going to a slash command, a mention reply, or a digest section.

### watchlist (`src/agent/watchlist/repository.py`)

Plain synchronous `sqlite3`. Two tables, `watched_containers` and `events`. Every
public function calls `init_db()` first (`CREATE TABLE IF NOT EXISTS`), so there is no
migration step and no ordering requirement at startup. `record_event()` trims events
older than 90 days on every write, so a crash-looping container cannot grow the log
forever. `find_watched_container()` goes through `resolve_one`, so watch-list lookups
behave exactly like container lookups.

Does not know about Docker, Discord, or the monitor that writes to it.

### alerting (`src/agent/alerting/discord.py`)

Message delivery, not policy. `send_alert()` posts one rich embed with a severity color
(info `0x3498DB`, warning `0xE67E22`, critical `0xE74C3C`). `_resolve_channel()` tries
the gateway cache and falls back to `fetch_channel`, because `get_channel()` is often
`None` right after `on_ready` before the cache fills. Errors are logged, never raised:
callers run inside `tasks.loop` jobs, and a raised exception kills the loop silently.

`post_report()` posts a multi-chunk report as one unit. A `ForumChannel` gets one
thread (the first chunk opens it, the rest are messages inside it); a text channel gets
one embed per chunk. It returns the id to key conversation memory to (the new thread id
for a forum, the channel id for a text channel), or `None` if nothing was posted.

Does not know why an alert is being sent.

### bot (`src/agent/bot/`)

The Discord layer, and the only place that knows about intents, interactions and
embeds.

- `client.py`: `run_bot()`. Intents are the defaults plus `message_content`, which is
  privileged; if it is not enabled the bot exits with a message naming the setting.
  `_Bot` subclasses `commands.Bot` only to override `close()` and call `close_memory()`
  first. `on_ready` is guarded by a module-level `_setup_done` flag because gateway
  reconnects re-fire it. It starts the monitor, starts the digests, syncs slash commands
  (guild sync when `DISCORD_GUILD_ID` is set, which is near-instant and good for
  testing, global sync otherwise), then attaches the Discord log handler.
  `DiscordLogHandler` forwards INFO and above to `DISCORD_LOG_CHANNEL_ID` through an
  `asyncio.Queue` drained by a pump task, so `emit()` never blocks. It drops any record
  whose logger name starts with `discord` to avoid a feedback loop, and posts a "Log
  forwarding active" line on startup so an empty channel means "nothing happening"
  rather than "broken". The `httpx` and `httpx2` loggers are pinned to WARNING because
  they emit one INFO line per HTTP call.
- `slash.py`: eleven commands on the application command tree: `/status`,
  `/investigate`, `/report`, `/digest [daily|weekly] [post_to_reports]`, `/containers`,
  `/watching`, `/watch`, `/unwatch`, `/watchlist`, `/reset`, `/help`. Long answers go
  out as multiple followups via `split_discord_text`. Watch-list and listing commands
  reply ephemerally. A tree-level `on_error` maps cooldown, missing permission and
  check failure to a readable ephemeral message.
- `monitor.py`: the background poll. See the second request flow below.
- `digest.py`: the scheduled reports. One `tasks.loop(time=...)` fires at
  `REPORT_HOUR_UTC`; it always posts the daily and additionally posts the weekly on
  `WEEKLY_REPORT_WEEKDAY` (0 = Monday). Both are skipped entirely when
  `DISCORD_REPORTS_CHANNEL_ID` is unset. The daily is the current snapshot plus every
  transition in the last 24 hours. The weekly is the snapshot plus, per target, outage
  count and total downtime over `DIGEST_LOOKBACK_DAYS`, computed by `_downtime()`
  pairing `down` and `up` events; an unclosed `down` is measured to now and flagged
  "still down". A target with two or more outages in the window counts as flapping and
  gets a **Why** section, which is the one place the model contributes to the details.
  After posting, the body is fed to `engine.seed()` on the returned thread id, so
  someone can @mention the bot under the report and it already has the report as
  context.
- `summarize.py`: `clean(raw, service=, action=)` sends raw tool output through the LLM
  for a readable summary and falls back to the truncated raw output if the LLM is
  unreachable or returns nothing. `_sanitize()` collapses whitespace and caps
  interpolated values at 200 characters so a service name cannot inject prompt lines.
  `discordify()` fixes markdown Discord cannot render: ATX `#` headings become **bold**
  (small models emit `####` even when told not to) and markdown tables become bullet
  lists, with content inside code fences left alone. Limits: 3500 characters of raw fed
  to the LLM, 1800 shown in a fallback code block, 1900 hard cap on anything returned.
- `utils.py`: `format_container_list()` groups containers by state with running first;
  `split_discord_text()` chunks at 1900 characters, preferring newline boundaries.

One wrinkle worth knowing: `workflows/investigate.py` imports `discordify` from
`bot/summarize.py`, which is an upward import, and `bot/digest.py` imports
`agent.workflows.investigate` and `agent.engine.seed` inside the functions that use
them rather than at module top.

## Request flow: a user asks a question

Both entry points converge on `investigate()`, and both key memory to the channel id,
so a slash command and a follow-up mention in the same channel share one thread.

```text
  Discord                                     Discord
  slash command                               message (DM or @mention)
      |                                             |
      v                                             v
  bot/slash.py                                bot/client.py on_message
  slash_investigate()                               |
      |                                             v
      |                                     workflows/nl.py handle_message()
      |                                       - skip bots and self
      |                                       - in a guild, require a mention
      |                                       - strip mention markup
      |                                             |
      +---------------------+-----------------------+
                            |
                            v
              workflows/investigate.py investigate(question, thread_id=channel id)
                            |
                            v
              engine.run(question,
                         tools_by_name=<10 tools>,
                         system_prompt=<Oracle>,
                         budget_prompt=<...>,
                         thread_id=<channel id>)
                            |
              +-------------+--------------------------------+
              |                                              |
              v                                              v
    memory.thread_config()                        memory.checkpointer()
    thread_id + recursion_limit +                 AsyncSqliteSaver on data/agent.db
    per-run objects (bound llm,
    tools_by_name, system prompt)
              |
              v
    +---------------------------------------------+
    |  compiled LangGraph (cached in engine._GRAPH)|
    |                                              |
    |   START --> model --(tool_calls)--> tools    |
    |               ^                       |      |
    |               +-----------------------+      |
    |               |                              |
    |          (no tool_calls)                     |
    |               v                              |
    |              END                             |
    +---------------------------------------------+
              |                        |
              |                        v
              |              tools/{docker,prometheus,loki}.py
              |                        |
              |                        v
              |              Docker Engine API / Prometheus / Loki
              v
    final AIMessage text
              |
              v
    bot/summarize.py discordify()      (headings -> bold, tables -> bullets)
              |
              v
    bot/utils.py split_discord_text()  (1900-char chunks)
              |
              v
    interaction.followup.send(...)  /  message.reply(...)
```

If the tool budget runs out, the `GraphRecursionError` never reaches the workflow:
the engine makes one final no-tools call and returns a summary. If anything else
raises, `investigate()` returns `"Investigation failed: ..."`. Either way the user
gets a message.

## Request flow: the monitor observes a state change

`start_monitor(bot)` is called from `on_ready`. The loop interval is
`max(MONITOR_INTERVAL_SECONDS, 10)` seconds.

```text
  tasks.loop(seconds = max(MONITOR_INTERVAL_SECONDS, 10))
        |
        +--> _poll_containers(bot)          [skipped unless DOCKER_MONITOR is true]
        |       |
        |       v
        |    docker.list_containers(all_containers=True)      -> [] if unreachable
        |       |                                                (one bad poll must
        |       |                                                 not kill the loop)
        |       v
        |    in_scope(name, watched)   <-- watchlist.list_watched_containers()
        |       |                          name contains DOCKER_NAME_FILTER
        |       |                          (empty filter = every container)
        |       |                          OR the name is on the /watch list
        |       v
        |    compare state with _container_state[name]   (in-memory dict)
        |       |
        |       +-- prev is None ................ baseline only, no alert
        |       |
        |       +-- running -> not running ...... record_event(name,'container','down')
        |       |                                 send_alert(ALERT_CHANNEL, critical)
        |       |
        |       +-- not running -> running ...... record_event(name,'container','up')
        |                                         send_alert(STATUS_CHANNEL, info)
        |
        |    then: names no longer seen are deleted from _container_state
        |
        +--> _poll_endpoints(bot)
                |
                v
             probe(url)   GET with redirects, up = status < 400,
                |         any HTTPError or OSError = down
                v
             compare with _endpoint_state[name]   (same three cases, kind='endpoint')
                |
                v
             record_event(name,'endpoint','up'|'down') + send_alert(...)

             then: endpoints removed from the configuration are dropped from the dict
                          |
                          v
             watchlist events table  ---->  bot/digest.py reads it for the
                                            daily and weekly reports
```

Two choices in there are deliberate. Container alerting reads the Docker socket
directly rather than going through PromQL, so there is no scrape gap to fall into and
no PromQL edge that mis-fires when Prometheus itself restarts; Prometheus is kept for
metrics, not for alerting. And the first observation of any target only baselines it
(`prev is None`), so restarting the bot never produces a wave of false transitions.

Endpoint polling covers what the Docker poll cannot see: a URL on another host, or a
service behind a proxy. It is configured with `MONITORED_ENDPOINTS` as a comma-separated
list of `name=url` pairs.

## Data model

One SQLite file, at `DB_PATH`, resolved in `src/agent/config/settings.py` from
`DATABASE_URL` (default `sqlite:///data/agent.db`) relative to the repo root. It holds
everything that has to survive a restart:

| table | written by | contents |
| --- | --- | --- |
| `watched_containers` | `watchlist/repository.py` | `name` (primary key), `created_at`. The `/watch` list. |
| `events` | `watchlist/repository.py` | `target`, `kind` (`container` or `endpoint`), `state` (`down` or `up`), `at`. Every monitor transition, trimmed to 90 days on write. |
| `checkpoints`, `writes` | LangGraph's `AsyncSqliteSaver` | Conversation state per `thread_id`. Created by `setup()`. |

Timestamps in `events` are SQLite `datetime('now')`, which is UTC, stored as
`YYYY-MM-DD HH:MM:SS`. `digest._downtime()` parses them back with exactly that format
and attaches `UTC`.

One file rather than two because a thread and the operational state it describes are
read together. A one-off script that posts a digest seeds the same thread the running
bot later answers in, and `/reset` deleting a thread is the same file operation as
`/unwatch` deleting a row. The two writers use different drivers (synchronous `sqlite3`
in the repository, `aiosqlite` under the async saver), which SQLite handles as two
connections to one file.

## Design decisions

**Read-only by construction.** The tool surface has no mutating call. `docker.py`
issues `GET /containers/json` and `GET /containers/{id}/logs` and nothing else; the
Prometheus and Loki tools only query. The system prompt tells the model it is read-only,
but that is reinforcement, not the guarantee. The guarantee is that there is no code
path to call. This also means the compose-file trick of mounting the Docker socket `:ro`
is not what makes it safe: that flag makes the socket *file* read-only while the Engine
API behind it stays fully writable, and socket access is root-equivalent on the host.

**A generic engine with injected tools and prompts.** `engine.py` takes
`tools_by_name`, `system_prompt` and `budget_prompt` per call. It never imports
`agent.tools`. That is why the eval notebooks can bind the same loop to a single tool to
measure that tool in isolation, why tests can pass fake tools that count their calls,
and why a future workflow with a narrower tool set does not touch the loop.

**Failure is always answered, never silent.** A tool that raises becomes
`(tool 'x' failed: ...)` in the transcript, which the model reads and works around. An
unknown tool name becomes `(unknown tool 'x')`. Budget exhaustion becomes a summary of
what was found so far. An LLM that is unreachable during `/status` becomes the raw tool
output in a code block. An alert that cannot be delivered is logged rather than raised,
because raising inside a `tasks.loop` job kills the loop. The mention handler catches
everything and replies with the error text. There is no path where the operator asks a
question and gets nothing back.

**Deterministic data, generated prose.** Digest numbers come from the `events` table and
the live snapshot, rendered by a template. The model writes the **Summary** on top and,
in the weekly, the **Why** paragraph for whatever flapped. The numbers are already exact,
so paraphrasing them could only lose or invent detail; the parts a template genuinely
cannot produce (reading a container's logs to explain a restart loop) are the parts the
model gets.

**One matching rule, and ambiguity raises.** Every name lookup goes through
`resolve_one`. A partial name that matches several candidates raises `AmbiguousName`
carrying the list, rather than returning whichever candidate came first. Silently
picking one would report the wrong container's state under the name the operator asked
for, which is worse than an error.

## Known limits

- **No cross-thread recall.** Memory is one conversation replayed per `thread_id`. The
  bot cannot connect something said in `#alerts` to something said in a DM.
- **Long threads evict their oldest turns.** `window()` trims to
  `MAX_CONTEXT_TOKENS` before every model call. A large seeded digest is the first
  thing to go, so "what did the report say?" stops working once the channel has enough
  conversation on top of it.
- **The monitor's live state is in-memory.** `_container_state` and `_endpoint_state`
  are module-level dicts. A restart re-baselines every target on the first poll, so
  transitions that happen while the bot is down are never recorded. The durable record
  is the `events` table, and it only contains what the monitor was running to see.
- **Digests have no missed-tick catch-up.** `tasks.loop(time=...)` fires at the next
  occurrence of the time. A bot that is down at `REPORT_HOUR_UTC` skips that day rather
  than posting late.
- **Container monitoring is opt-in.** `_poll_containers` returns immediately unless
  `DOCKER_MONITOR` is true, and container tools return empty results when the Docker
  socket is not mounted. Endpoint polling is unaffected either way.
