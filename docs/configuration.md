# Configuration

Every setting is an environment variable. `.env.example` at the repo root is the
starting point: copy it to `.env` and fill it in. The groups below follow the
order of that file.

Settings are declared in `src/agent/config/settings.py` as a pydantic-settings
`Settings` model, instantiated once at import as the module-level `settings`
object. Two variables (`DOCKER_HOST`, `LANGSMITH_TRACING`) are not fields on that
model and are read straight from the process environment by the code that needs
them; they are documented in their groups below.

## Discord

| Variable | Default | Meaning |
| --- | --- | --- |
| `DISCORD_BOT_TOKEN` | `""` | Bot token from the Discord developer portal. Required. |
| `DISCORD_GUILD_ID` | unset | Guild to sync slash commands to. Set it for near-instant command sync; leave it empty for a global sync. |
| `DISCORD_ALERT_CHANNEL_ID` | unset | Channel that receives down alerts (critical embeds). |
| `DISCORD_STATUS_CHANNEL_ID` | unset | Channel that receives recovery notes (info embeds). |
| `DISCORD_REPORTS_CHANNEL_ID` | unset | Channel for the daily and weekly digests. A forum channel gets one thread per digest. |
| `DISCORD_LOG_CHANNEL_ID` | unset | Channel that mirrors the bot's own log records at INFO and above. |

`DISCORD_BOT_TOKEN` is the only setting the process cannot start without.
`agent.bot.client.run_bot` raises `RuntimeError("DISCORD_BOT_TOKEN is not set")`
before it ever contacts Discord.

The four channel ids each gate one feature, and an unset id turns that feature
off quietly:

- No `DISCORD_ALERT_CHANNEL_ID`: down transitions are still written to the
  `events` table in SQLite, but nothing is posted. Same for
  `DISCORD_STATUS_CHANNEL_ID` and recovery transitions
  (`src/agent/bot/monitor.py`).
- No `DISCORD_REPORTS_CHANNEL_ID`: `agent.bot.digest.post` logs
  `skipping <kind> digest: DISCORD_REPORTS_CHANNEL_ID is unset` and returns. The
  scheduled task still runs; it just has nowhere to post. `/digest` still previews a report in the channel
  you invoke it from; only its `post_to_reports` option needs the id.
- No `DISCORD_LOG_CHANNEL_ID`: `_attach_discord_log_handler` returns immediately
  and logs go to the console only.

When log forwarding is wired up the handler posts one line,
`Log forwarding active (INFO and above).`, on startup, so an otherwise silent
channel means nothing is happening rather than something is broken. Records
whose logger name starts with `discord` are dropped to avoid a feedback loop,
and the `httpx` / `httpx2` loggers are pinned to WARNING because they emit one
INFO line per HTTP call.

## Endpoint monitoring

| Variable | Default | Meaning |
| --- | --- | --- |
| `MONITORED_ENDPOINTS` | `""` | Comma-separated `name=url` pairs, probed every cycle. Empty disables endpoint monitoring. |
| `MONITOR_INTERVAL_SECONDS` | `60` | Seconds between poll cycles. Floored at 10. |

Format, as parsed by `_endpoints()` in `src/agent/bot/monitor.py`:

```bash
MONITORED_ENDPOINTS="prometheus=http://localhost:9090/-/healthy,loki=http://localhost:3100/ready,api=https://api.example.internal/health"
```

Splitting is on `,` then on the first `=`, so a URL may contain `=` in a query
string. Names and URLs are stripped of surrounding whitespace, and any entry
without an `=`, without a name, or without a URL is skipped rather than raising.
The same list also feeds the `list_services` tool
(`src/agent/tools/docker.py`), so an endpoint named here is a name the agent can
talk about.

A probe is a GET with redirects followed and a 10 second timeout. Up means a
status below 400; any `HTTPError` or `OSError` counts as down. Only transitions
alert. The first observation of a target baselines it without alerting, so
restarting the bot never produces a false edge, and an endpoint removed from the
list is dropped from the in-memory state on the next cycle.

The interval is applied as `max(MONITOR_INTERVAL_SECONDS, 10)`, so values below
10 are silently raised to 10. Each cycle does one HTTP GET per endpoint plus, if
container monitoring is on, one Docker container listing.

## Digests

| Variable | Default | Meaning |
| --- | --- | --- |
| `REPORT_HOUR_UTC` | `5` | Hour (UTC) at which the digest task fires, once a day. |
| `WEEKLY_REPORT_WEEKDAY` | `0` | Weekday on which the weekly roll-up is posted in addition to the daily. 0 is Monday. |
| `DIGEST_LOOKBACK_DAYS` | `7` | Window the weekly roll-up counts outages and downtime over. |

One `discord.ext.tasks.loop(time=...)` fires at `REPORT_HOUR_UTC`. It always
posts the daily, and on `WEEKLY_REPORT_WEEKDAY` it posts the weekly as well.
`tasks.loop(time=...)` has no catch-up for missed ticks, so a bot that is down at
that hour skips that day rather than posting late.

Both digests go to `DISCORD_REPORTS_CHANNEL_ID` and are skipped when it is unset.
After posting, the report body is seeded into the conversation thread for the
posted message, so an @mention under the report starts with the report already in
context.

`DIGEST_LOOKBACK_DAYS` only affects the weekly. The daily always covers the last
24 hours. Note that the events table itself is trimmed to 90 days on every write
(`src/agent/watchlist/repository.py`), which is the real ceiling on a lookback
window.

## LLM

| Variable | `.env.example` | Code default | Meaning |
| --- | --- | --- | --- |
| `LLM_BASE_URL` | `http://localhost:11434/v1` | `http://100.64.0.7:4000/v1` | Base URL of an OpenAI-compatible chat completions API. |
| `LLM_MODEL` | `mistral` | `marconi-llm` | Model name passed to that API. |
| `LLM_API_KEY` | `sk-optional` | `""` | Bearer key for that API. Many self-hosted servers ignore it. |

The code defaults for `LLM_BASE_URL` and `LLM_MODEL` in `settings.py` point at a
specific lab endpoint and are not what you want on a new host. `.env.example` is
the intended starting point; set both explicitly.

Any OpenAI-compatible server works: Ollama, vLLM, llama.cpp's server, or a
LiteLLM proxy in front of something else. The client is built in
`src/agent/llm/client.py` with `temperature=0.0` and a 60 second timeout.

If the endpoint is unreachable the bot still starts and Discord commands still
respond: investigations return `Investigation failed: ...` and summarised
command output falls back to the raw tool text.

## Monitoring and logging backends

| Variable | Default | Meaning |
| --- | --- | --- |
| `PROMETHEUS_URL` | `http://localhost:9090` | Base URL of the Prometheus HTTP API. |
| `LOKI_URL` | `http://localhost:3100` | Base URL of the Loki HTTP API. |
| `PROMETHEUS_TOKEN` | `""` | Bearer token for Prometheus. Sent only when non-empty. |
| `LOKI_TOKEN` | `""` | Bearer token for Loki. Sent only when non-empty. |

Both clients (`src/agent/tools/prometheus.py`, `src/agent/tools/loki.py`) build
their headers from `_headers()`, which returns `{}` when the matching token is
empty and `{"Authorization": "Bearer <token>"}` when it is set. Nothing is sent
to an unauthenticated backend.

Label names given to the label-value tools are validated against
`^[A-Za-z_][A-Za-z0-9_]*$` before they are interpolated into a URL path, which
rejects `/`, `?`, `#`, `..` and whitespace. A rejected label returns no values
rather than an error.

Loki's instant `query_loki` tool does not use Loki's `/query` endpoint, because
Loki refuses plain log-stream selectors there. It runs a 15 minute range query
instead. That 15 minutes is fixed in code, not configurable.

## Docker discovery

| Variable | Default | Meaning |
| --- | --- | --- |
| `DOCKER_HOST` | `unix:///var/run/docker.sock` | Docker Engine endpoint. `tcp://host:2375` for a remote daemon. |
| `DOCKER_MONITOR` | `false` | Poll containers every cycle and alert on stop and restart. |
| `DOCKER_NAME_FILTER` | `""` | Only containers whose name contains this substring are in monitoring scope. Empty means all. |

`DOCKER_HOST` is not a `Settings` field. `_docker_host()` in
`src/agent/tools/docker.py` reads it as
`os.environ.get("DOCKER_HOST") or "unix:///var/run/docker.sock"`. The `or` is
deliberate: `.env` files and compose files commonly set `DOCKER_HOST=` empty, and
an empty string reaching the transport breaks every Docker call. Leave it unset
or empty for the normal local socket.

With `DOCKER_MONITOR=false` the container half of the poll returns immediately.
The Docker tools (`/status`, `/containers`, `list_services`, `docker_logs`) still
work, and endpoint monitoring still runs; what is off is unattended container
alerting.

Scope is decided per container by `in_scope()`:

```python
return (not name_filter) or (name_filter in name.lower()) or (name in watched)
```

So `DOCKER_NAME_FILTER` and the `/watch` list are a union, not an intersection.
An empty filter puts every container in scope, and the watch list then adds
nothing. A filter like `marconi` narrows monitoring to containers whose name
contains that substring (the comparison is case-insensitive on both sides), and
`/watch some-other-container` adds one container back in without widening the
filter. `/watch` accepts a partial or separator-variant name (`agent_api`,
`agent-api` and `agentapi` all match) and stores the resolved exact container
name, which is what the scope check compares against.

Container alerting reads the Docker socket directly rather than going through
PromQL, so it has no scrape gap and does not mis-fire when Prometheus itself
restarts.

## Agent loop limits

| Variable | Default | Meaning |
| --- | --- | --- |
| `MAX_TOOL_STEPS` | `10` | Tool-calling budget for one investigation. |
| `MAX_CONTEXT_TOKENS` | `12000` | Context budget for a single model turn. Older messages in a thread are trimmed past it. |
| `LOKI_MAX_LIMIT` | `500` | Upper clamp on the number of log lines a Loki tool may request. |
| `RANGE_MAX_HOURS` | `6` | Upper clamp on the window of a range query. |

`MAX_TOOL_STEPS` becomes `recursion_limit = 2 * MAX_TOOL_STEPS` in
`memory.thread_config()`, because one model turn costs two graph steps (model,
then tools). Exhausting it is not an error: `engine.run` catches
`GraphRecursionError` and makes one final no-tools call over the checkpointed
thread, so an over-budget run still returns a summary of what it found. Raising
this lets a harder diagnosis finish; lowering it caps the cost of a runaway
question.

`MAX_CONTEXT_TOKENS` is passed to `trim_messages` in `memory.window()` with the
approximate token counter, applied before every model call. It bounds one turn,
not the stored thread: SQLite keeps the whole conversation, and the window is the
tail that gets sent. A long-running channel therefore forgets its oldest turns
first, which includes a large seeded digest.

`LOKI_MAX_LIMIT` clamps the `limit` argument of `query_loki` and
`query_loki_range` into `[1, LOKI_MAX_LIMIT]`. It bounds what one tool call can
pull back, and the returned string is truncated to 4000 characters regardless.

`RANGE_MAX_HOURS` clamps the `minutes` argument of `query_prometheus_range` and
`query_loki_range` into `[1, RANGE_MAX_HOURS * 60]`. For Prometheus the range
also fixes resolution: the step is `max(15, minutes * 60 // 100)` seconds, so a
window is always about 100 points or fewer.

## Storage

| Variable | Default | Meaning |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///data/agent.db` | SQLite file holding the watch list, the event log, and conversation checkpoints. |

One file holds everything: `watched_containers` and `events`
(`src/agent/watchlist/repository.py`) and the LangGraph checkpoints
(`src/agent/memory.py`). A script and the running bot therefore see the same
threads.

The path is resolved once, at import of `agent.config.settings`:

```python
DB_PATH = Path(settings.database_url.replace("sqlite:///", ""))
if not DB_PATH.is_absolute():
    DB_PATH = Path(__file__).resolve().parents[3] / DB_PATH
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
```

Three consequences. The value is only a SQLite path with the `sqlite:///` prefix
stripped, so no other database backend is supported. A relative path is resolved
against the repo root, not the working directory, so the file is the same one
whichever directory you launch from. And the parent directory is created at
import time, before anything opens the file.

## Tracing

| Variable | Default | Meaning |
| --- | --- | --- |
| `LANGSMITH_TRACING` | `false` | Enables LangSmith tracing of LLM calls. |

This is not a `Settings` field. The LangChain runtime reads it from the process
environment, along with the other `LANGSMITH_*` variables (an API key and
optionally a project name) that it needs to actually upload traces. It is off in
`.env.example` because tracing adds an upload, and a retry stall when the
endpoint is slow, to every LLM call. Turn it on when you are actively reading the
LangSmith dashboard.

## How settings are loaded

`agent.config.settings` calls `load_env()` at import, which uses python-dotenv's
`find_dotenv()` to locate the nearest `.env` walking up from the current working
directory, then loads it with `override=False`. Real environment variables
therefore win over `.env`. `agent/cli.py` calls `load_env()` again before
importing anything else. The `Settings` model itself also declares
`env_file=".env"`.

Two parsing details matter when you edit `.env`:

- `env_parse_none_str=""` means a variable that is present but empty parses as
  `None`. That is what makes `DISCORD_ALERT_CHANNEL_ID=` a valid way to leave an
  optional integer channel id unset, instead of a validation error on an empty
  string.
- That rule would also turn empty string fields into `None`, so a
  `model_validator(mode="before")` walks the incoming data and puts any `str`
  field that arrived as `None` back to `""`. This is why `DOCKER_NAME_FILTER=`
  and `PROMETHEUS_TOKEN=` behave as empty strings rather than crashing on
  `.lower()` or a truthiness check.

`extra="ignore"` means unknown variables in `.env` are not an error, so the file
can carry variables for other tooling.

## Security

`.env` is not committed: `.gitignore` excludes `.env*`. `.env.example` is
tracked (git ignore rules do not apply to files already under version control)
and is the only env file in the repository. `.dockerignore` also excludes
`.env`, so the token never enters an image layer; compose passes it in at
runtime via `env_file: .env`.

The Discord bot token grants full control of the bot account. Treat
`PROMETHEUS_TOKEN` and `LOKI_TOKEN` the same way. All three belong in the
environment or in `.env`, never in a compose file or a committed config. Rotate
the bot token in the Discord developer portal if it leaks; nothing in this repo
caches it.

Backend tokens are only sent when set. With `PROMETHEUS_TOKEN` and `LOKI_TOKEN`
empty, requests to those backends carry no `Authorization` header at all, which
is the right behaviour for an unauthenticated instance on a private network and
the wrong one for a backend exposed to the internet: set the tokens in that case.
