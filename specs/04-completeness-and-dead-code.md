# 04 — Completeness & Dead Code 🟡

Things that exist but aren't connected, or deliverables that are one small wire away from
"done." Most are honest MVP scoping — the point here is to make the gaps explicit and cheap
to close for the demo.

---

## 4.1 Discord alerting is built but never triggered

**Files:** `src/agent/alerting/discord.py` (helper), `src/agent/workflows/incident.py`
(never calls it), `docs/workflows.md` step 6 ("(Optional) Send a Discord alert")

`send_alert()` works, but no workflow invokes it, and `discord_alert_channel_id` /
`discord_guild_id` settings are defined but read nowhere. So the "Alert delivery through
Discord" / "basic alerting capability" deliverable is a helper function, not a feature.

**Fix (small, high demo value):** after `store_incident(...)` in the incident workflow, if
`settings.discord_alert_channel_id` is set, post the summary to that channel. Needs a handle
to the running bot — simplest for the demo is to have the `!incident` command send the
summary to the alert channel itself after computing it.

---

## 4.2 Prometheus/Loki source helpers are wired to nothing

**Files:** `src/agent/tools/sources/prometheus.py`, `.../loki.py`, `.../base.py`

`query_prometheus` / `query_loki` are implemented, but `get_service_metrics` and
`get_recent_logs` return hardcoded stubs and never call them. So "monitoring/logging
integration" is present as code but produces no real data. The `Source` ABC in `base.py` has
**no implementers** — a speculative abstraction (ponytail: delete until a second source
justifies it).

**Fix for the demo:** make `get_service_metrics` call `query_prometheus` with a real PromQL
expression for the service, and `get_recent_logs` call `query_loki`. Even one working query
turns a stub into a genuine integration. Delete `base.py` unless a real polymorphic use
appears.

---

## 4.3 `docker`, `ssh`, and `health` tools are unreachable

**Files:** `src/agent/tools/docker.py`, `ssh.py`, `health.py`

These are implemented (docker has the 1.2 bug) but are exposed by **no** bot command, **no**
API route, and **no** workflow step. From a user's perspective they're dead code — only
reachable via direct import in tests.

**Fix:** either surface a couple of them (e.g. a `!health <url>` command, a
`GET /health-check?url=` route) so they count toward "controlled agent tools," or note in the
README that they're library-only building blocks. Right now the README/usage docs list
commands for status/logs/metrics/incident only, so these tools are undocumented too.

---

## 4.4 Incident id is computed but never surfaced

**Files:** `src/agent/workflows/incident.py:31`, `src/agent/api/routes.py:35`

`store_incident()` returns a new id, but `run_incident_workflow` discards it and returns only
the summary. So a user can't take the result of `POST /incidents/{service}` and then fetch its
report — the report workflow (`run_report_workflow(incident_id)`) has no id to feed it.

**Fix:** return `{"incident_id": id, "summary": summary}` from the workflow/route so the
create → report loop is usable end to end.

---

## 4.5 Redundant / confused DB migration

**File:** `src/agent/storage/repository.py:30-34`

`init_db()` creates the table already including a `status` column, then immediately tries
`ALTER TABLE ... ADD COLUMN status` and swallows the resulting `OperationalError`. On a fresh
DB the ALTER **always** fails (column exists) and is caught. It's dead-on-arrival: either the
table is new (has status) or old (this "migrates" it) — but as written the CREATE guarantees
the column, so the ALTER can never succeed. Harmless but misleading.

**Fix (ponytail):** delete the try/except ALTER block. `CREATE TABLE IF NOT EXISTS` with the
status column is sufficient for the MVP. If you truly need to migrate pre-existing DBs, check
`PRAGMA table_info` first — but for an MVP with a throwaway `data/agent.db`, just drop it.
