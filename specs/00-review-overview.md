# Review Overview — Marconi Infrastructure Operations Agent

**Reviewed:** 2026-07-15 · **Scope:** full repository (src, tests, docs, docker, config)
**Verdict:** Solid MVP skeleton, clean structure and passing tests — but **two confirmed
runtime bugs break the flagship "incident workflow" deliverable on both of its real entry
points (Discord + API)**, and the project depends on an obscure non-standard HTTP package
(`httpx2`) where the standard `httpx` would do.

The code is well-organized and appropriately small for an MVP. Most gaps are honest,
documented stubs. The issues below are the ones that either break a deliverable, pose a
risk, or are cheap wins.

## Deliverable coverage (per Phase II goals)

| Deliverable | State | Notes |
|---|---|---|
| Discord bot interface + commands | ⚠️ Partial | `!status/!logs/!metrics` work; **`!incident` crashes** (see 01) |
| Backend service + API | ⚠️ Partial | routes wired; **`POST /incidents/{service}` crashes** (see 01) |
| Controlled tools (logs/metrics/status) | ✅ Stubs | intentional, documented placeholders |
| Monitoring/logging integration | ⚠️ Stub only | Prometheus/Loki helpers exist but nothing calls them |
| Self-hosted LLM integration | ✅ | works via OpenAI-compatible client (config caveat, see 03) |
| Incident investigation workflow | ⚠️ Broken paths | logic exists; only the CLI path runs (see 01) |
| Alerting via Discord | ⚠️ Not wired | `send_alert()` helper exists but no workflow calls it (see 04) |
| Data storage | ✅ | SQLite repository works, tested |
| Testing w/ simulated issues | ✅ | 15 pass / 1 skip; scenario files present (gaps in 05) |
| Documentation | ✅ | setup/usage/architecture/workflows all present |

## Severity index

| # | Severity | Title |
|---|---|---|
| 01 | 🔴 High | `asyncio.run()` inside running loop breaks incident workflow (API + bot) |
| 01 | 🔴 High | Docker unix-socket calls use sync transport on `AsyncClient` |
| 02 | 🟠 Med | Command-injection surface in SSH tools; no auth on API |
| 03 | 🟠 Med | `httpx2` dependency (obscure, non-standard); `.env.example` API-key alias mismatch |
| 04 | 🟡 Low | Dead/unwired components: alerting, sources, docker/ssh/health tools, langgraph |
| 05 | 🟡 Low | Test & correctness cleanups (non-hermetic SSH test, redundant migration, etc.) |

See the numbered spec files for detail, evidence, and fixes.
