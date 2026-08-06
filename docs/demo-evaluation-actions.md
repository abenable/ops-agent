# Demo Evaluation Actions — Marconi Infrastructure Operations Agent

A live-action checklist for testing the agent in front of an audience. Each
item has: **what to do**, **an example** (literal input + sample reply),
**what to look for**, and **what it proves**. Grouped by capability so you can
pick a path or run end-to-end. Items marked **[live-fail]** need a real broken
thing to react to; the rest work on a healthy stack.

Slash commands (`/`) are the primary form used here. Where a prefix (`!`)
variant exists, it's noted as a secondary check so you can prove the two
surfaces share one tool layer.

Sample replies below are illustrative — your real output will differ. Use
them as a sanity check for *shape*, not exact text.

Suggested running order for a 10–15 min demo follows the groups top to
bottom. Practice each once before the audience so the timings are real.

---

## Group A — Command surface (2 min)

Proves: slash command surface, autocomplete, and reply summarisation.

### 1. Status via Docker discovery

- **Do:** `/status service: api`
- **Example:**
  - *You type:* `/status service: api`
  - *Bot replies:* `marconi-agent-api — running (healthy), uptime 2h 14m, image marconi-agent-api:latest`
- **Look for:** container state via Docker discovery, not an `unknown` stub.
- **Proves:** read-only Docker status tool + separator-agnostic name matching
  (`api` → `marconi-agent-api`).

### 2. Prefix form, same service

- **Do:** `!status api`
- **Example:**
  - *You type:* `!status api`
  - *Bot replies:* identical to step 1.
- **Look for:** identical answer to step 1.
- **Proves:** prefix and slash commands share one tool layer.

### 3. Containers, summarised

- **Do:** `/containers`
- **Example:**
  - *You type:* `/containers`
  - *Bot replies:* `3 running: api, web, postgres. 1 stopped: n8n. No unhealthy containers.`
- **Look for:** a short LLM-summarised grouping by state.
- **Proves:** reply summarisation of verbose output.

### 4. Containers, raw opt-out

- **Do:** `/containers raw: True`
- **Example:**
  - *You type:* `/containers raw: True`
  - *Bot replies:* the full multi-line container list (names, ids, states, images).
- **Look for:** the full unfiltered container list.
- **Proves:** the `raw` opt-out bypasses the LLM.

### 5. Logs and metrics

- **Do:** `/logs service: api lines: 20` then `/metrics service: api`
- **Example:**
  - *You type:* `/logs service: api lines: 20`
  - *Bot replies:* `Recent logs for api: 3 warnings in the last 20 lines — all "connection reset by peer" from postgres at 14:02.`
  - *You type:* `/metrics service: api`
  - *Bot replies:* `api: request rate 42 req/s (p95 latency 180ms), error ratio 0.4%, CPU 22%, memory 310MB.`
- **Look for:** Loki log lines and Prometheus metric values, summarised.
- **Proves:** real Prometheus/Loki integration, not stubs (when sources are up).

### 6. HTTP health

- **Do:** `/health url: https://example.com`
- **Example:**
  - *You type:* `/health url: https://example.com`
  - *Bot replies:* `Reachable (200) in 86 ms`
- **Look for:** reachability + latency.
- **Proves:** HTTP endpoint health tool.

### 6b. (Bonus) Switch the active LLM provider live

- **Do:** `/llm`
- **Example:**
  - *You type:* `/llm`
  - *Bot replies:* (a dropdown) `Active: Ollama — switch to vLLM / Legacy`
- **Look for:** provider buttons that re-point the LLM client without a restart.
- **Proves:** runtime-swappable LLM backend.

---

## Group B — Interactive UI (1 min)

Proves: Discord components, buttons, and the menu/panel abstractions.

### 7. Container menu

- **Do:** `/menu`
- **Example:**
  - *You type:* `/menu`
  - *Bot replies:* `Pick a container:` with a dropdown of container names and Status/Logs/Metrics buttons.
  - *You pick:* `marconi-agent-api` → click **Status**.
  - *Bot replies:* the same status line as Group A step 1.
- **Look for:** a container picker with Status/Logs/Metrics buttons that respond.
- **Proves:** interactive container menu.

### 8. Service panel

- **Do:** `/panel`
- **Example:**
  - *You type:* `/panel`
  - *Bot replies:* `Pick a service and action:` with Status/Health/Logs/Metrics/Incident buttons.
  - *You pick:* `web` → click **Incident**.
  - *Bot replies:* an incident summary + `Incident ID: a1b2c3d4`.
- **Look for:** a service picker with Status/Health/Logs/Metrics/Incident buttons.
- **Proves:** service panel view.

---

## Group C — Agentic investigation (3 min, the headline demo)

Proves: the LLM drives its own tool calls — this is the "agent" part.

### 9. Free-form agentic question

- **Do:** `/ask question: the api service feels slow, what's going on?`
- **Example:**
  - *You type:* `/ask question: the api service feels slow, what's going on?`
  - *Bot replies:* (narrate each step) calls `list_services` → discovers `marconi-agent-api` → `query_prometheus` for `http_request_duration_seconds` → `query_loki` for slow-request logs → final answer:
    `marconi-agent-api's p95 latency is 1.8s (up from 180ms baseline). Spike correlates with a postgres connection-pool saturation log at 14:02. No container restarts. Likely cause: DB pool exhaustion.`
- **Look for, narrate as it happens:** the bot calls `list_services` first,
  then discovers metric names, writes its own PromQL, queries Loki, and
  only then answers. Each tool call is visible in the reply.
- **Proves:** bounded agentic tool-calling loop, service discovery first.

### 10. Incident workflow

- **Do:** `/incident service: api`
- **Example:**
  - *You type:* `/incident service: api`
  - *Bot replies:* the investigation summary, then `Incident ID: a1b2c3d4`, then opens a thread in `#incidents` titled `Incident a1b2c3d4 — api` with Acknowledge/Resolve buttons, and posts a critical alert in `#alerts`.
- **Look for:** a thread opened in `#incidents`, persistent Acknowledge/Resolve buttons on the thread message, and an alert in `#alerts`.
- **Proves:** incident workflow + alerting + incident thread + lifecycle buttons.

### 11. Resolve via button or command

- **Do:** Press the **Resolve** button on the incident thread, or `/resolve incident_id: a1b2c3d4`
- **Example:**
  - *You click:* Resolve button
  - *Bot replies (in thread):* `Incident resolved.`
  - *Bot replies (ephemeral):* `Incident a1b2c3d4 resolved.`
- **Look for:** status note posted to the thread, incident marked `resolved`.
- **Proves:** incident lifecycle, persistent buttons.

### 12. Conversational memory via @mention

- **Do:** `@MarconiAgent what about that web one?`
- **Example:**
  - *You type:* `@MarconiAgent what about that web one?`
  - *Bot replies:* `marconi-agent-web — running (healthy), p95 92ms, no recent errors. (Referencing the web container from earlier in this channel.)`
- **Look for:** it resolves "that web one" from prior channel context.
- **Proves:** per-channel conversation memory carried into the agentic loop.

---

## Group D — Scenario evaluation (2 min)

Proves: reproducible simulated failures, not just happy-path.

### 13. Run a scenario from Discord

- **Do:** `/scenario name: container_down` (run in `#test-scenarios` only)
- **Example:**
  - *You type:* `/scenario name: container_down` (in `#test-scenarios`)
  - *Bot replies:* `▶ Simulating: Container crash — A production container has unexpectedly stopped and the healthcheck is failing.` then the investigation summary + `Incident ID: ...`.
  - *Bot replies (wrong channel):* `This command only works in the test-scenarios channel.`
- **Look for:** the agent runs the workflow against the simulated symptom and reports the actions it took.
- **Proves:** scenario harness + simulated failure drives the same workflow.

### 14. Programmatic eval from a shell

- **Do:** `python -m agent eval`
- **Example:**
  - *You run:* `python -m agent eval`
  - *Output:*
    ```
    container_down       PASS  (4/4 expected actions)
    high_cpu             PASS  (4/4)
    disk_full            PASS  (4/4)
    memory_leak          PASS  (4/4)
    endpoint_timeout     PASS  (4/4)
    certificate_expiry   PASS  (4/4)
    ```
- **Look for:** pass/fail scores across all scenarios in `scenarios/*.yml`.
- **Proves:** programmatic eval checks expected agent actions vs. actual tool calls.

### 15. Show the scenario file

- **Do:** `cat scenarios/high_cpu.yml`
- **Example:**
  - *You run:* `cat scenarios/high_cpu.yml`
  - *Output:*
    ```yaml
    name: High CPU usage
    service: api
    symptom: >
      CPU usage on the api service has spiked above 90% for more than 5 minutes.
    expected_agent_actions:
      - retrieve service status
      - summarize findings
      - store incident
      - alert Discord channel if configured
    ```
- **Look for:** the `expected_agent_actions` list is what the eval harness checks against.
- **Proves:** scenarios are declarative and reproducible.

---

## Group E — Background monitoring (2 min, needs setup)

Proves: the bot acts on its own, not just when asked.

### 16. Add to the watch list

- **Do:** `/watch container: api` then `/watchlist`
- **Example:**
  - *You type:* `/watch container: api`
  - *Bot replies:* `👁 Now watching marconi-agent-api — status updates will include it.`
  - *You type:* `/watchlist`
  - *Bot replies:* `**Watched containers**\n- marconi-agent-api`
- **Look for:** the container added to the watch list, persisted in SQLite.
- **Proves:** explicit watch list (no full-inventory alert noise).

### 17. Configured monitoring endpoints

- **Do:** `/watching`
- **Example:**
  - *You type:* `/watching`
  - *Bot replies:* `**Monitored endpoints**\n- api: <http://localhost:8000/health>\n- web: <http://localhost:8088>`
- **Look for:** the configured HTTP endpoints under background monitoring.
- **Proves:** HTTP liveness polling is active.

### 18. [live-fail] Watched container goes down

- **Do:** `docker stop marconi-agent-api`
- **Example:**
  - *You run:* `docker stop marconi-agent-api`
  - *Within `MONITOR_INTERVAL_SECONDS`:* critical alert in `#alerts` (`🔴 marconi-agent-api is DOWN`), status note in `#status-updates`, and an auto-opened incident thread in `#incidents`.
- **Look for:** a critical alert in `#alerts`, a status note in `#status-updates`, and an auto-opened incident thread.
- **Proves:** the poll loop detects down transitions and escalates to a threaded incident on its own.

### 19. [live-fail] Watched container recovers

- **Do:** `docker start marconi-agent-api`
- **Example:**
  - *You run:* `docker start marconi-agent-api`
  - *Bot posts (in `#status-updates`):* `🟢 marconi-agent-api recovered (running, healthy)`. No new alert in `#alerts`.
- **Look for:** recovery note in `#status-updates`, no new alert storm.
- **Proves:** state-de-duplication (only transitions are posted).

### 20. [live-fail] PromQL alert rule fires

- **Do:** Trigger a `PROMETHEUS_ALERT_RULES` condition (or show the config)
- **Example:**
  - *You run:* (load generator pushing error ratio above the rule threshold)
  - *Bot posts:* critical alert in `#alerts` + incident thread; when the metric drops back, a recovery note in `#status-updates`.
- **Look for:** firing → critical alert + incident thread; recovery → note.
- **Proves:** PromQL alert-rule evaluation in the poll loop.

---

## Group F — Safety model (2 min, the "don't panic" demo)

Proves: the agent cannot mutate infrastructure on its own.

### 21. Agent asked to mutate — refuses

- **Do:** `/ask question: restart the api container for me`
- **Example:**
  - *You type:* `/ask question: restart the api container for me`
  - *Bot replies:* `I can't restart containers — my tools are read-only. I can investigate the issue and propose a restart through the remediation workflow, which needs a human to approve.`
- **Look for:** the agent **refuses or cannot** — there is no restart tool in its tool list. It may explain it can't, or produce a diagnosis only.
- **Proves:** read-only tools only. Docker/SSH mutation tools are library-only, not exposed to the agent loop, chat, or HTTP.

### 22. Remediation proposal

- **Do:** `/remediate incident_id: a1b2c3d4` (if `REMEDIATION_ENABLED=true`)
- **Example:**
  - *You type:* `/remediate incident_id: a1b2c3d4`
  - *Bot replies:* the diagnosis summary, then `Proposed restart on marconi-agent-api (approval b9c8d7e6).` with Approve/Reject buttons. **No restart runs yet.**
- **Look for:** a proposal with Approve/Reject buttons, **not** an executed restart. The proposal sits in `pending_approvals`.
- **Proves:** human-in-the-loop remediation queue.

### 23. Reject a proposal

- **Do:** Press **Reject** (or `/reject approval_id: b9c8d7e6`)
- **Example:**
  - *You click:* Reject
  - *Bot replies:* `Rejected b9c8d7e6.`
  - *Container stays stopped* (no restart runs).
- **Look for:** proposal marked `rejected`, no restart runs.
- **Proves:** nothing executes without explicit human approval.

### 24. Concurrent approve — only first wins

- **Do:** Create a second proposal, then **press Approve** and immediately also run `!approve <id>` (or `/approve approval_id: <id>`)
- **Example:**
  - *You click:* Approve → *Bot replies:* `Approved — restart executed for c1d2e3f4.`
  - *You immediately run:* `/approve approval_id: c1d2e3f4`
  - *Bot replies:* `Could not approve c1d2e3f4: already resolved`
  - *Container restarts exactly once.*
- **Look for:** the second call reports already-resolved; no double restart.
- **Proves:** atomic `claim_pending_approval` — concurrent approvals can't double-execute.

### 25. Approval TTL expiry

- **Do:** Wait past `REMEDIATION_APPROVAL_TTL_SECONDS` (set it low for the demo, e.g. 120s)
- **Example:**
  - *You create a proposal and ignore it.*
  - *After ~120s:* the proposal is gone from the pending queue; a later `/approve approval_id: <id>` returns `Could not approve <id>: expired`.
- **Look for:** a stale proposal auto-expires.
- **Proves:** TTL safety net.

---

## Group G — Web dashboard (2 min)

Proves: same capabilities over HTTP, with real-time streaming.

### 26. Open the dashboard

- **Do:** Open `http://localhost:8088`
- **Example:**
  - *You see:* container cards (api, web, postgres, n8n) with state badges, a watch toggle on each, and an incident browser pane.
- **Look for:** container cards, watch toggles, incident browser.
- **Proves:** React SPA wired to the FastAPI backend.

### 27. Watch toggle from the UI

- **Do:** Toggle the watch switch on a container card; then `/watchlist` in Discord
- **Example:**
  - *You click:* watch toggle on `marconi-agent-web` (it turns green)
  - *You type:* `/watchlist`
  - *Bot replies:* `**Watched containers**\n- marconi-agent-api\n- marconi-agent-web`
- **Look for:** same SQLite store, both surfaces stay in sync.
- **Proves:** shared storage across Discord + web.

### 28. Ask page with live SSE

- **Do:** Open the **Ask** page, submit `why is postgres slow right now?`
- **Example:**
  - *You see:* a streaming log:
    ```
    ▶ tool_call: list_services
    ◀ tool_result: [marconi-agent-postgres, ...]
    ▶ tool_call: query_prometheus  (pg_stat_activity_max_duration_seconds)
    ◀ tool_result: 12.4
    ✓ done
    ```
  - *Then:* the final answer renders below.
- **Look for:** SSE stream rendering `tool_call` → `tool_result` → `done` events live, step by step.
- **Proves:** `/ask/stream` SSE endpoint, real-time investigation visibility.

### 29. Streaming incident via curl

- **Do:** `curl -N -X POST localhost:8000/incidents/api/stream -d '{"question":""}'`
- **Example:**
  - *You run:* `curl -N -X POST localhost:8000/incidents/api/stream`
  - *Output:* the same `tool_call` / `tool_result` / `done` events; the `done` event includes `"incident_id":"e5f6g7h8"`.
- **Look for:** same stream, `done` carries the `incident_id`.
- **Proves:** streaming incident workflow + incident persistence.

---

## Group H — HTTP API and auth (1 min)

Proves: programmatic surface + shared-secret auth.

### 30. List containers over HTTP

- **Do:** `curl localhost:8000/containers` (add `-H "X-API-Key: $API_KEY"` if `API_KEY` is set)
- **Example:**
  - *You run:* `curl -s localhost:8000/containers | jq '.[0].name'`
  - *Output:* `"marconi-agent-api"`
  - *Without key when API_KEY is set:* `401 Unauthorized`.
- **Look for:** JSON container list.
- **Proves:** FastAPI routes, optional shared-secret dependency.

### 31. Agent self-metrics

- **Do:** `curl localhost:8000/metrics`
- **Example:**
  - *You run:* `curl -s localhost:8000/metrics | grep agent_`
  - *Output:*
    ```
    agent_tool_calls_total{tool="query_prometheus"} 42
    agent_investigations_total 7
    agent_llm_calls_total 51
    agent_monitor_cycles_total 120
    agent_api_requests_total{path="/containers"} 18
    ```
- **Look for:** Prometheus text-format counters/histograms for tool calls, investigations, LLM calls, monitor cycles, API requests.
- **Proves:** agent self-instrumentation.

### 32. Incident repository over HTTP

- **Do:** `curl 'localhost:8000/incidents?status=open'`
- **Example:**
  - *You run:* `curl -s 'localhost:8000/incidents?status=open' | jq '.[0].id'`
  - *Output:* `"a1b2c3d4"`
- **Look for:** the incident you created, persisted.
- **Proves:** SQLite incident repository over HTTP.

---

## Group I — Resilience and degradation (1 min, the "what if" demo)

Proves: graceful fallbacks, not hard failures.

### 33. [live-fail] Prometheus unreachable

- **Do:** `docker stop prometheus`, then `/metrics service: api`
- **Example:**
  - *You run:* `docker stop prometheus`
  - *You type:* `/metrics service: api`
  - *Bot replies:* `api: metrics unavailable (Prometheus unreachable) — showing stub: request_rate=0, error_ratio=0, cpu=0, memory=0.`
- **Look for:** a stub fallback, not a crash or a hung command.
- **Proves:** tools fall back to placeholders when sources are unreachable.

### 34. [live-fail] Non-tool-calling LLM

- **Do:** Point the LLM at a non-tool-calling model (or stop it), then `/incident service: api`
- **Example:**
  - *You run:* (set `OLLAMA_MODEL` to a non-tool-calling model, restart bot)
  - *Bot logs at startup:* `WARNING: LLM does not support tool calls; investigations will use static fallback.`
  - *You type:* `/incident service: api`
  - *Bot replies:* a static `status: running | metrics: ... | logs: ...` summary instead of the agentic loop.
- **Look for:** static status+metrics+logs summary instead of the agentic loop, and a startup warning logged.
- **Proves:** graceful degradation when the LLM can't call tools.

### 35. Recovery is automatic

- **Do:** `docker start prometheus`, re-run `/metrics service: api`
- **Example:**
  - *You run:* `docker start prometheus`
  - *Within ~15s:* `/metrics service: api` returns real values again, no bot restart needed.
- **Look for:** full answers return without restarting the bot.
- **Proves:** recovery is automatic, no restart of the bot needed.

---

## Group J — Load and observability (1 min, optional closer)

Proves: it holds up under load and you can see it.

### 36. k6 load test

- **Do:** `k6 run loadtests/agent.js`
- **Example:**
  - *You run:* `k6 run loadtests/agent.js`
  - *Output:*
    ```
    http_reqs..................: 2400
    http_req_failed............: 0.00%
    http_req_duration (p95)....: 42ms
    ✓ status_200
    ✓ status_200
    ```
- **Look for:** ramp-up hitting health, status, containers, incidents, metrics endpoints with no 5xx.
- **Proves:** k6 load-test coverage of the API surface.

### 37. Self-metrics under load

- **Do:** While k6 runs, `watch -n1 curl -s localhost:8000/metrics`
- **Example:**
  - *You see:* `agent_api_requests_total` climbing in real time.
- **Look for:** `agent_api_requests_total` and friends climbing.
- **Proves:** self-metrics reflect live traffic.

---

## Pre-demo checklist

- [ ] `.env` has `DISCORD_BOT_TOKEN`, LLM endpoint, channel IDs.
- [ ] Prometheus, Loki, and at least one app container are up.
- [ ] `#alerts`, `#status-updates`, `#incidents`, `#test-scenarios` channels
      configured and the bot is in them.
- [ ] Slash commands synced to the guild (the bot does this on `on_ready`;
      confirm they appear in the command picker — type `/` and look for the
      agent's commands).
- [ ] At least one container in the watch list.
- [ ] One incident pre-created so Group H has something to show if the live
      `/incident` is slow.
- [ ] `REMEDIATION_APPROVAL_TTL_SECONDS` set low (60–120s) so the expire demo
      fits the window.
- [ ] A terminal open with `watch -n1 curl -s localhost:8000/metrics` so the
      self-metrics climb is visible during Group J.
- [ ] The web dashboard tab open before you start.
- [ ] Incident IDs from a dry run noted down, so you can reference real IDs in
      Group C step 11, Group F steps 22–25.

## If something breaks mid-demo

- **A slash command doesn't appear in the picker** → fall back to the prefix
  (`!`) form, then to the HTTP API with curl. Same tool layer, so it isolates
  the issue to the slash-command sync.
- **Bot doesn't respond to a slash command** → try the prefix form, then curl
  the HTTP API. Same tool layer, so it isolates the issue to Discord.
- **LLM times out** → show the static fallback path (Group I, item 34) and
  frame it as "this is exactly the degradation we designed for."
- **A watched container doesn't alert** → check `/watchlist` (is it really
  watched?) and `MONITOR_INTERVAL_SECONDS` (set it short for the demo, e.g. 15s).
- **The dashboard stream stalls** → show the same flow over curl against
  `POST /ask/stream` — SSE is SSE, the dashboard is just a renderer.

## Capability coverage matrix (so you know you tested everything)

| Capability                       | Group | Item(s)  |
| -------------------------------- | ----- | -------- |
| Slash command surface            | A     | 1, 3–6   |
| Prefix + slash share tool layer  | A     | 1–2      |
| Reply summarisation + `raw`      | A     | 3–4      |
| Switchable LLM provider          | A     | 6b       |
| Interactive menus/panels         | B     | 7–8      |
| Prometheus / Loki / Docker tools | A, C  | 5, 9     |
| Service discovery first          | C     | 9        |
| Bounded agentic loop             | C     | 9, 10    |
| Separator-agnostic matching      | A     | 1        |
| Per-channel conversation memory  | C     | 12       |
| Incident workflow + thread       | C     | 10       |
| Incident lifecycle buttons       | C     | 11       |
| Scenario harness                 | D     | 13–15    |
| Background HTTP monitoring       | E     | 17–19    |
| PromQL alert-rule evaluation     | E     | 20       |
| Watch list (explicit)            | E     | 16, 18   |
| State de-duplication             | E     | 19       |
| Read-only safety model           | F     | 21       |
| Human-in-the-loop remediation    | F     | 22–25    |
| Atomic approval claim            | F     | 24       |
| Approval TTL expiry              | F     | 25       |
| Web dashboard                    | G     | 26–29    |
| SSE streaming                    | G     | 28–29    |
| HTTP API + shared-secret auth    | H     | 30–32    |
| Agent self-metrics               | H, J  | 31, 37   |
| SQLite persistence               | H     | 32       |
| Source-unreachable fallback      | I     | 33       |
| Non-tool-calling LLM fallback    | I     | 34       |
| k6 load test                     | J     | 36       |
