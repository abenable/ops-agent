# Project Goals

This document updates the original internship charter for the AI-Powered Infrastructure Operations Agent to reflect the state of the MVP as it stands today.

## Main Goal

Deliver a working MVP of an AI-powered infrastructure operations agent that lives in Discord, helps the infrastructure team inspect selected systems, investigates issues through a self-hosted language model, and produces clear operational summaries — all through controlled, read-only tools.

## Objectives

### 1. Architecture connecting Discord, backend, monitoring, storage, and LLM

**Status:** Delivered.

The system runs as two entry points (Discord bot + FastAPI backend) sharing a single SQLite store, a shared LLM client, and a common set of tools. The architecture wires Discord messages, HTTP requests, background monitoring loops, and incident workflows into one codebase.

- Discord ↔ bot commands and @mention handler
- FastAPI routes expose the same capabilities over HTTP
- SQLite incident repository persists incidents and their lifecycle
- OpenAI-compatible LLM client powers agentic investigation and summaries

### 2. Controlled agent tools and workflows

**Status:** Delivered.

Implemented:

- Prometheus metric discovery and PromQL queries
- Loki log queries
- HTTP endpoint health checks
- Service discovery (`list_services`) so the LLM learns real container/endpoint names first
- Read-only Docker container status and logs tools for containers Prometheus/Loki do not tag
- Separator-agnostic service-name matching (`agent_api` finds `marconi-agent-api`)
- Incident investigation workflow (bounded tool-calling loop)
- Incident lifecycle: open, acknowledge, resolve, with persistent action buttons
- Docker and SSH mutation tools as library-only utilities for future workflows
- Human-in-the-loop remediation: the remediation agent proposes restart actions, which
  sit in a pending-approval queue until a human approves or rejects them via Discord
  buttons or `!approve`/`!reject` commands.

By design, actions that can mutate infrastructure (Docker restart, SSH systemctl restart) are **not** exposed to the agent loop, chat, or HTTP. The current tools are read-only; future write actions will require explicit human approval.

### 3. Discord integration

**Status:** Delivered.

The bot handles:

- Prefix commands (`!`) and slash commands (`/`) sharing one tool layer, for `status`, `containers`, `logs`, `metrics`, `health`, `ask`, `incident`, `scenario`, `ack`, `resolve`, `watching`, `watch`, `unwatch`, `watchlist`, `menu`, `panel`, `info`
- Reply summarisation of verbose output through the LLM, with a `raw` opt-out
- Conversational replies via @mention or DM using the same agentic loop
- Interactive container menu and service panel with action buttons
- Background monitoring alerts, status transitions, and incident threads in purpose-specific channels
- Scenario simulation restricted to a configured test-scenarios channel

### 4. Documentation and demonstration

**Status:** Documentation delivered; demonstration expected.

- README, setup guide, usage guide, architecture, workflows, tools reference, and channel mapping are in `docs/`.
- The scenario directory provides reproducible test cases.
- A final demo is expected to show the agent checking status, investigating an issue, summarizing findings, and generating an incident response.

## Expected Deliverables

| Deliverable | Status | Notes |
| --- | --- | --- |
| Working MVP integrated with Discord | Delivered | Bot + API + SQLite + LLM toolchain running together |
| Discord bot interface | Delivered | Prefix + slash commands, @mention/DM replies, interactive menus, reply summarisation, channel-specific outputs |
| Agent backend and tooling | Delivered | Read-only Prometheus/Loki/Docker tools + service discovery; read/write Docker/SSH tools library-only |
| Self-hosted LLM integration | Delivered | OpenAI-compatible endpoint; tool-calling models preferred, graceful fallback otherwise |
| Monitoring and logging integration | Delivered | Prometheus + Loki sources with fallback stubs; Prometheus self-metrics endpoint for the agent itself |
| Technical documentation | Delivered | Lives in `docs/` and this README |
| Scenario evaluation harness | Delivered | `agent/eval` + `tests/test_eval.py` + `python -m agent eval` CLI |
| k6 load-test scripts | Delivered | `loadtests/agent.js` covers health, status, containers, incidents, and metrics |
| Web dashboard | Delivered | React SPA at `web/`, served via nginx on port 8088 |
| n8n monitoring integration | Delivered | n8n in compose stack, scraped by Prometheus, logs shipped via promtail to Loki |
| Final demonstration | Pending | Scheduled end-of-internship demo using real or scenario-driven cases |

## What Changed Since the Original Charter

- **Read-only MVP first.** Mutation actions (restart services, change configurations) were deferred to a later phase with human approval rather than being built into the MVP.
- **Service status via Docker discovery.** `!status` now reports real container state through Docker container discovery with separator-agnostic name matching, instead of the original `unknown` stub.
- **Agentic loop over static reports.** The LLM now writes its own PromQL/LogQL during investigations, discovers real service names first, and can inspect containers with read-only Docker tools.
- **Slash commands.** A slash (`/`) command surface with autocomplete now runs alongside the prefix (`!`) commands, sharing one tool layer.
- **Background monitoring inside the bot.** HTTP and Docker endpoint polling plus PromQL alert evaluation run in the Discord bot process rather than requiring a separate monitor.
- **SQLite over a larger database.** Single-node SQLite is sufficient for the MVP and reduces deployment surface.
- **Eval harness and agent self-metrics.** Programmatic scenario evaluation and Prometheus self-instrumentation were added for ongoing quality assessment.
- **Container watch list.** Only explicitly-selected containers are monitored, preventing alert noise from the full Docker inventory.

## Remaining Work and Future Extensions

- Add a multi-environment source registry (prod / staging monitoring sources).
- Re-register incident action views on startup from open incidents in SQLite, so the buttons keep working after a redeploy.
- Implement human-in-the-loop approval before any Docker/SSH write action is executed.
- Persist monitor/alert state so de-duplication survives restarts.
- Introduce RBAC for command channels and sensitive tools.
- Expand the eval harness scenario coverage and integrate k6 load tests into CI.
- Build Prometheus recording rules and Grafana dashboards for agent self-metrics.
