# Workflows

## Incident investigation workflow

`agent.workflows.incident.run_incident_workflow(service)` — async, returns
`{incident_id, summary}`.

1. Start a bounded, read-only tool-calling loop (`run_agentic_investigation`).
   The LLM can call:
   - `list_services` (discover real container + endpoint names; call this first)
   - `list_metric_names` / `get_label_values` (Prometheus discovery)
   - `query_prometheus` / `query_prometheus_range` (PromQL)
   - `query_loki` (LogQL)
   - `docker_status` / `docker_logs` (read-only container inspection)
2. Tool results are truncated to 4,000 chars and fed back to the model.
3. The loop runs at most `MAX_TOOL_STEPS` (default 6) times and stops when the
   model returns a final answer instead of a tool call.
4. If the LLM fails or produces no usable answer, fall back to the static
   status+metrics+logs summary.
5. Persist the incident to SQLite and return its id + summary.

`run_ask_workflow(question)` uses the same loop for free-form questions without
storing an incident.

Triggers: `!incident <service>` / `/incident`, `!ask <question>` / `/ask`,
`POST /incidents/{service}`, `python -m agent incident`, or the background
monitor. For Discord triggers the bot also opens an incident thread (with
persistent Acknowledge/Resolve buttons) and posts an alert (see below).

## Monitoring workflow

`agent.bot.monitor` runs every `MONITOR_INTERVAL_SECONDS`.

### HTTP-endpoint liveness

For each `MONITORED_ENDPOINTS` entry:

1. `check_endpoint(url)` — reachable and status `< 500` counts as **up**.
2. Compare to the previous state (kept in memory):
   - any up↔down change → post to the status channel;
   - healthy→down → post a critical alert **and** run the incident workflow, opening a thread.
3. Store the new state.

### PromQL alert rules

For each `PROMETHEUS_ALERT_RULES` entry:

1. `query_prometheus(expr)` — a rule is **firing** when the result set is non-empty.
2. Compare to the previous state (kept in memory):
   - not-firing→firing → post a critical alert **and** run the incident workflow, opening a thread;
   - firing→not-firing → post a recovery note to the status channel.
3. Store the new state.

Prometheus/Loki queries use a 10s timeout and optional bearer tokens from
`PROMETHEUS_TOKEN` / `LOKI_TOKEN`.

### Container watch-list monitoring

When `DOCKER_MONITOR=true`, the poll loop also inspects every container in the
**watch list** each cycle:

1. `docker.list_containers(all_containers=True)` returns the full container list.
2. Only containers whose name appears in the watch list are considered.
3. A container that transitions from `running` to a non-running state triggers a
   critical alert to `#alerts`.
4. The periodic status snapshot (`STATUS_SNAPSHOT_INTERVAL_SECONDS`) writes the
   state of all watched containers to `#status-updates`.

Containers not in the watch list are silently ignored. The watch list is persisted
in SQLite and can be edited via `!watch`/`!unwatch`/`!watchlist`, the web
dashboard toggle, or the Watch button in `!menu`.

## Remediation workflow

When the agentic investigation produces a diagnosis, a human can invoke the
remediation workflow with `!remediate <incident_id>`:

1. `run_remediation_workflow(incident_id, service, diagnosis)` runs its own
   tool-calling loop that can propose restarts.
2. Each proposal is persisted as a `pending_approvals` row and displayed in
   Discord with Approve/Reject buttons (`RemediationApprovalView`).
3. `!approve <approval_id>` / `!reject <approval_id>` (or the buttons) resolve
   the proposal.
4. Stale proposals auto-expire after `REMEDIATION_APPROVAL_TTL_SECONDS` (default
   300 s).  Set `REMEDIATION_ENABLED=false` as a global kill switch.

## Streaming

The agentic investigation loop has SSE streaming variants for the web dashboard:

| Endpoint | Description |
| --- | --- |
| `POST /ask/stream` | SSE stream with `{question}`; yields `tool_call`, `tool_result`, `done` |
| `POST /incidents/{service}/stream` | Same stream; the `done` event also carries the `incident_id` |

The Ask page in the web dashboard renders these events in real time, showing
each tool call and its result as the investigation progresses.

## Evaluation

`python -m agent eval` runs all scenarios in `scenarios/*.yml` through the live
LLM and reports pass/fail scores.  For automated verification without a live LLM,
`pytest tests/test_eval.py` runs each scenario with mocked LLM responses against
the action-to-tool mapping defined in the `agent.eval` module.

## Incident lifecycle

1. Incident created (`open`) by the incident workflow.
2. `!ack <id>` / `/ack <id>` → status `acknowledged`; a note is posted to the incident thread if present.
3. `!resolve <id>` / `/resolve <id>` → status `resolved`; a note is posted to the incident thread if present.

The incident thread message also carries Acknowledge/Resolve buttons
(`IncidentActionView`, `timeout=None`) so they never expire while the bot is
running.

## Reporting workflow

`agent.workflows.reporting.run_report_workflow(incident_id)`:

1. Look up the incident by id in SQLite.
2. Return a formatted report string (or a not-found message).

Trigger: `python -m agent report --incident-id <id>`.

## Extending workflows

The tools prefer real sources (Prometheus/Loki/Docker) and fall back to stubs
when a source is unreachable. To add signal sources, extend
`get_service_metrics` / `get_recent_logs` or add a new tool, register it in the
`TOOLS` list in `agent.workflows.incident`, and mention it in the system prompt.
