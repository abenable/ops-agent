# Configuration

Everything is environment variables, read by `agent/config/settings.py` from
the process environment and the nearest `.env`. Copy `.env.example` to `.env`
to start.

Blank is treated as unset for string settings, so a placeholder like
`DOCKER_HOST=` in a compose file behaves as if it were absent.

## Discord

| Variable | Default | Purpose |
|---|---|---|
| `DISCORD_BOT_TOKEN` | none | Required. The bot token. |
| `DISCORD_GUILD_ID` | unset | Sync slash commands to one guild (instant) instead of globally (up to an hour). |
| `DISCORD_ALERT_CHANNEL_ID` | unset | Where down-alerts go. Unset disables them. |
| `DISCORD_STATUS_CHANNEL_ID` | unset | Where recovery notices and the periodic status snapshot go. Unset disables the snapshot. |
| `DISCORD_REPORTS_CHANNEL_ID` | unset | Where scheduled digests go. Unset disables them. A forum channel works, and each digest opens its own thread. |
| `DISCORD_INCIDENT_CHANNEL_ID` | unset | Where an agent investigation is posted when a PromQL rule starts firing. Unset skips the investigation entirely. |
| `DISCORD_TEST_SCENARIOS_CHANNEL_ID` | unset | Where `scripts/run_scenario.py` posts its verdicts. |
| `DISCORD_LOG_CHANNEL_ID` | unset | Mirror INFO+ logs into Discord, batched into one message per second. |

## LLM

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `google` | `openai` for any OpenAI-compatible endpoint, `google` for Gemini/Gemma. |
| `LLM_MODEL` | `gemma-4-26b-a4b-it` | Model name, without a provider prefix. |
| `LLM_SUMMARIZER_MODEL` | blank | Cheaper model for context summarization. Blank reuses `LLM_MODEL`. |
| `LLM_BASE_URL` | `http://localhost:11434/v1` | `openai` provider only. Exported as `OPENAI_API_BASE`. |
| `LLM_API_KEY` | blank | `openai` provider only. Exported as `OPENAI_API_KEY`. Many self-hosted endpoints accept any value. |
| `GEMINI_API_KEY` | blank | `google` provider only. Exported as `GOOGLE_API_KEY`. |

The provider and model are combined into a `provider:model` identifier
(`settings.model_id`) and handed to `create_agent`. Credentials reach the client
through the environment; see [architecture.md](architecture.md#the-model).

## Agent behaviour

| Variable | Default | Purpose |
|---|---|---|
| `MAX_TOOL_STEPS` | `10` | Tool calls allowed per run. The call that would exceed it is not executed and the run ends. Counts **tool calls**, not model turns. |
| `MAX_CONTEXT_TOKENS` | `12000` | Threshold at which `SummarizationMiddleware` compresses older turns into a summary. |
| `LOKI_MAX_LIMIT` | `500` | Hard cap on log lines any Loki query may return. |
| `RANGE_MAX_HOURS` | `6` | Hard cap on the window of any range query. |

## Data sources

| Variable | Default | Purpose |
|---|---|---|
| `PROMETHEUS_URL` | blank | Blank leaves the four Prometheus tools out of the agent's tool set entirely. |
| `LOKI_URL` | blank | Blank leaves the three Loki tools out. |
| `PROMETHEUS_TOKEN` | blank | Sent as `Authorization: Bearer` when set. |
| `LOKI_TOKEN` | blank | Same, for Loki. |
| `DOCKER_HOST` | `unix:///var/run/docker.sock` | Set `tcp://host:2375` for a remote daemon. |

## Monitoring

| Variable | Default | Purpose |
|---|---|---|
| `DOCKER_MONITOR` | `false` | Poll containers and alert when one stops. |
| `DOCKER_NAME_FILTER` | blank | Only track containers whose name contains this. Blank tracks every container. The watch list is added on top either way. |
| `MONITORED_ENDPOINTS` | blank | Comma-separated `name=url` pairs polled each cycle. Blank disables endpoint probes. |
| `MONITOR_INTERVAL_SECONDS` | `60` | Poll interval. Floored at 10s. |
| `PROMETHEUS_ALERT_RULES` | blank | Comma-separated `name=promql` rules evaluated each cycle. A rule fires when its query returns any series. Only the first `=` separates the name, so `up == 0` works. |

## Scheduled digests and status

| Variable | Default | Purpose |
|---|---|---|
| `REPORT_HOUR_UTC` | `5` | Hour (UTC) the daily digest posts. `5` is 08:00 in EAT (UTC+3). |
| `WEEKLY_REPORT_WEEKDAY` | `0` (Monday) | Weekday the weekly digest also posts. |
| `DIGEST_LOOKBACK_DAYS` | `7` | Window the weekly digest summarizes. |
| `STATUS_INTERVAL_HOURS` | `2` | How often the status snapshot posts. Floored at 1h. |

The digest hour is expressed in UTC, not local time, so a deployment in another
zone has to convert. The weekly digest posts on its weekday in addition to the
daily one, both at the same hour.

## The HTTP API

| Variable | Default | Purpose |
|---|---|---|
| `API_HOST` | `0.0.0.0` | Interface `agent api` binds. |
| `API_PORT` | `8000` | Port `agent api` binds. |
| `API_KEY` | unset | When set, every route except `/health` requires a matching `X-API-Key`. Unset leaves the API open. |

## Storage

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///data/agent.db` | The watch list and event log. Relative paths resolve against the repo root. |

Conversation checkpoints live in `memory.db` beside it, derived rather than
configured separately, and opened only by `agent/memory.py`.

## Tracing

`LANGSMITH_TRACING=false` by default. Enabling it adds an upload and retry stall
to every LLM call, so only turn it on if you are actively reading the LangSmith
dashboard.

## A gotcha

`LLM_PROVIDER`, `LLM_API_KEY`, `GEMINI_API_KEY`, and `DISCORD_BOT_TOKEN` are
declared with a `validation_alias`. In code, `Settings(llm_provider="google")`
is silently ignored, and only `Settings(LLM_PROVIDER="google")` populates it.
This bites when constructing `Settings` in tests. From the environment it works
as you would expect.
