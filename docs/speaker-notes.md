# Speaker Notes — Marconi Infrastructure Operations Agent (~3 min)

Pacing target: ~420 spoken words at a steady 140 wpm. Section timings are
guidance, not hard cuts. Speak the **[Bracketed]** cues silently as your own
signposts.

---

## [0:00–0:25] Hook & one-line framing

"I built an AI infrastructure-operations agent that lives in Discord.

Instead of operators SSH-ing into boxes, pasting dashboards, and stitching
together logs and metrics by hand, they message the bot. It discovers the real
service names, writes its own PromQL and LogQL, inspects containers, and
returns a clean operational summary — through controlled, read-only tools."

---

## [0:25–0:55] The problem and the shape of the solution

"The team runs services in Docker, with Prometheus for metrics and Loki for
logs. When something breaks, the toil is the glue: *which* container, *what*
metric, *which* log line. This project removes that glue work.

It's an MVP built during the Marconi industrial training, Implementation
Phase, weeks five through eight. It has two entry points sharing one codebase:
a Discord bot for operators, and a FastAPI backend for everything else —
scripts, the web dashboard, load tests. Both share one SQLite store, one
LLM client, and one set of tools."

---

## [0:55–1:30] Architecture, top to bottom

"Top of the funnel: Discord users on one side, HTTP clients on the other.

Discord carries two surfaces — prefix commands like `!status` and slash
commands like `/status`, plus @mention and DM conversational replies. They
all hit the same tool layer. There's also an interactive container menu and a
service panel with action buttons.

Underneath sits the agent workflow engine — incident investigation,
remediation, reporting. The workflow runs a bounded agentic loop: the LLM
calls `list_services` first to learn real names, then discovers Prometheus
metrics and labels, writes its own PromQL and LogQL, and can inspect
containers with read-only Docker tools. The loop is capped at six tool steps.

Around that loop: the LLM client — any OpenAI-compatible endpoint, so it runs
self-hosted on Ollama, vLLM, or llama.cpp. The SQLite store for incidents and
watch lists. The alerting layer that posts to purpose-specific Discord
channels. And the tool layer at the bottom, which talks to Prometheus, Loki,
and Docker."

---

## [1:30–2:05] Background monitoring and incident lifecycle

"The bot isn't just reactive. A background poll loop runs every cycle and does
three checks: HTTP endpoint liveness, PromQL alert-rule evaluation, and the
watched-containers list. Watched means explicit — `!watch` or a toggle in the
web dashboard — so we don't get alert noise from every container on the host.

On a healthy-to-down transition it posts a critical alert and auto-opens a
threaded incident. Incidents have a full lifecycle: open, acknowledged,
resolved — driven from persistent buttons on the thread message, with the
`!ack` and `!resolve` commands as restart-safe fallbacks."

---

## [2:05–2:30] Safety model — read-only by design

"The key design decision: every tool the agent can call is read-only. Docker
restart and SSH systemctl restart exist in the codebase but are library-only —
they are **not** exposed to the agent loop, to chat, or to HTTP.

For remediation, there's a human-in-the-loop path: the agent proposes a
restart, that proposal sits in a pending-approvals table, and a human must
press Approve or Reject in Discord. The claim is atomic, so a double-click or
a button-plus-command race can't double-execute the restart. Stale proposals
auto-expire."

---

## [2:30–2:50] Web dashboard, eval, observability, load testing

"Beyond Discord there's a React single-page dashboard: container cards, watch
toggles, an incident browser, and an Ask page that streams the agentic
investigation in real time over SSE — you watch each tool call and result as
it happens.

For quality, a YAML scenario eval harness runs the agent through simulated
failures — container crash, disk full, memory leak, certificate expiry — and
checks its tool calls against expected actions. The agent also instruments
itself: Prometheus counters and histograms at `GET /metrics` for tool calls,
investigations, LLM calls, monitor cycles, and API requests. And k6 load-tests
stress the API endpoints."

---

## [2:50–3:00] Close

"So, end to end: an operator messages Discord, the agent investigates through
read-only tools against real Prometheus, Loki, and Docker sources, writes its
own queries, summarizes the findings, tracks the incident through
acknowledge and resolve, watches endpoints in the background, and never
mutates infrastructure without a human pressing Approve. That's the MVP."

---

## Quick-reference: if you forget where you are

- **0:00** — what it is, one sentence
- **0:25** — problem + two entry points share one codebase
- **0:55** — architecture diagram, top to bottom
- **1:30** — background monitoring + incident lifecycle
- **2:05** — read-only safety model + human-in-the-loop remediation
- **2:30** — web dashboard, eval harness, self-metrics, k6
- **2:50** — close, full loop in one breath

## If asked a follow-up, have these ready

- **Why SQLite, not Postgres?** Single-node, one bot instance, small
  deployment surface. Listed as a limitation for concurrent writers.
- **Why a bounded loop?** Six tool steps keeps latency and cost predictable;
  the static status+metrics+logs fallback covers non-tool-calling models.
- **Separator-agnostic matching?** `agent_api` finds `marconi-agent-api`, so
  operators don't have to remember the exact container spelling.
- **What degrades?** If Prometheus or Loki is unreachable, tools fall back to
  stubs rather than failing hard. If the LLM can't call tools, the
  investigation falls back to a static summary.
- **What's explicitly out of scope?** RBAC, multi-environment sources,
  persistent monitor state across restarts, and re-registering incident
  buttons after a redeploy — all listed as future work in the README.
