# Architecture

The agent is a single Python process: a Discord bot with an embedded
LLM-driven investigation loop.

**The bot process is the backend.** The tools, the LLM client, and the SQLite
store all live in-process; Discord is the only transport and the only client.
An earlier iteration also exposed the same operations over a FastAPI service,
but its only consumer was the web dashboard — once the dashboard was cut, the
HTTP layer was an interface with zero callers, so it was removed rather than
maintained. If a non-Discord client ever appears, `investigate.py` and
`tools/` are plain async functions that a thin API can reuse unchanged.

```
Discord user
   │  /status · /investigate · /report · @mention · DM
   ▼
┌────────────────────────────────────────────────────┐
│ bot (discord.py)                                   │
│   slash.py      — slash commands                   │
│   client.py     — connection, DM/mention handler,  │
│                   Discord log forwarding           │
│   monitor.py    — background container poll loop   │
│   summarize.py  — LLM cleanup of raw tool output   │
└──────┬───────────────────────────────┬─────────────┘
       │ /investigate, /report, chat   │ container transitions
       ▼                               ▼
┌────────────────────┐          ┌────────────────────┐
│ investigate.py     │          │ alerting/discord.py│
│ tool-calling loop  │          │ alert embeds       │
└──────┬─────────────┘          └────────────────────┘
       │ bind_tools(ALL_TOOLS)
       ▼
┌────────────────────────────────────────────────────┐
│ tools/ (all read-only)                             │
│   docker.py      — Engine API: list/status/logs    │
│   prometheus.py  — instant + range PromQL,         │
│                    metric/label discovery          │
│   loki.py        — LogQL range queries, labels     │
└──────┬───────────────┬───────────────┬─────────────┘
       ▼               ▼               ▼
   Docker socket   Prometheus      Loki
```

The LLM (any OpenAI-compatible self-hosted endpoint, configured via
`LLM_BASE_URL`/`LLM_MODEL`) drives the loop in `investigate.py`: it receives
the question, calls tools, reads the results, and answers — at most
`MAX_TOOL_STEPS` tool rounds, after which it must summarize what it has.

Supporting stores:

- **SQLite** (`data/agent.db`, via `memory/repository.py`) — the watched-container
  list managed with `/watch`, `/unwatch`, `/watchlist`.
- **In-memory monitor state** (`bot/monitor.py`) — last known container and endpoint state,
  used to fire down/recovery alerts on transitions. Rebuilt on every restart;
  the first poll baselines without alerting.

## Data flow per feature

- **`/status`** — gather container states (Docker) + configured endpoints →
  `summarize.clean()` asks the LLM for a concise health summary → reply.
- **`/investigate` / mention / DM** — the question goes into the tool-calling
  loop; the final answer is normalized for Discord markdown and replied,
  chunked to the 2000-char limit.
- **`/report <service>`** — same loop, fixed incident template (Summary →
  What happened → Evidence → Likely cause → Recommended next steps).
- **Alerts** — the monitor loop compares container states and endpoint
  reachability across polls; a down transition posts a critical embed to
  `#alerts`, a recovery posts a note to `#status-updates`. Scope: containers
  matching `DOCKER_NAME_FILTER` plus the watch list, and every
  `MONITORED_ENDPOINTS` entry. The first observation of anything only
  baselines it, so a restart never alerts.

## Safety boundaries

- Every tool exposed to the LLM is **read-only**: container list/status/logs,
  Prometheus queries, Loki queries. There is no restart/config-change tool,
  so the model cannot affect infrastructure; it can only recommend actions.
- Tool outputs and loop length are capped (`MAX_TOOL_STEPS`, `LOKI_MAX_LIMIT`,
  `RANGE_MAX_HOURS`, per-tool output truncation) to bound cost and prompt size.
- User-supplied service names never reach a shell; Docker access is via the
  Engine API over the local socket, and Prometheus/Loki via HTTP GET only.

## Known limitations

See the README's Limitations section — in short: tool-calling model required,
no PromQL alert rules, in-memory monitor state, no RBAC, single-node SQLite.
