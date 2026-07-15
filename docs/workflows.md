# Workflows

## Incident investigation workflow

`agent.workflows.incident.run_incident_workflow(service)` — async, returns
`{incident_id, summary}`.

1. Collect service status (`get_service_status`).
2. Collect recent metrics (`get_service_metrics` → Prometheus, else stub).
3. Collect recent logs (`get_recent_logs` → Loki, else stub).
4. Build a prompt and call the self-hosted LLM (`ainvoke`); on failure, fall back to a summary
   that embeds the raw context.
5. Persist the incident to SQLite and return its id + summary.

Triggers: `!incident <service>`, `POST /incidents/{service}`, `python -m agent incident`, or
the background monitor. For Discord triggers the bot also opens an incident thread and posts an
alert (see below).

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

## Incident lifecycle

1. Incident created (`open`) by the incident workflow.
2. `!ack <id>` → status `acknowledged`; a note is posted to the incident thread if present.
3. `!resolve <id>` → status `resolved`; a note is posted to the incident thread if present.

## Reporting workflow

`agent.workflows.reporting.run_report_workflow(incident_id)`:

1. Look up the incident by id in SQLite.
2. Return a formatted report string (or a not-found message).

Trigger: `python -m agent report --incident-id <id>`.

## Extending workflows

The tools already prefer real sources (Prometheus/Loki) and fall back to stubs. To add signal
sources, extend `get_service_metrics` / `get_recent_logs` (or add a new tool) and include the
new signal in `run_incident_workflow`. `get_service_status` is still a stub — wire it to your
service inventory to make status reporting real.
