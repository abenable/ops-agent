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

**Status:** Mostly delivered.

Implemented:

- Prometheus metric discovery and PromQL queries
- Loki log queries
- HTTP endpoint health checks
- Incident investigation workflow (bounded tool-calling loop)
- Incident lifecycle: open, acknowledge, resolve
- Docker and SSH tools as library-only utilities for future workflows

Still a stub:

- `!status` service status is not yet wired to a real service registry or orchestrator (`unknown` placeholder).

By design, actions that can mutate infrastructure (Docker restart, SSH systemctl restart) are **not** exposed to the agent loop, chat, or HTTP. The current tools are read-only; future write actions will require explicit human approval.

### 3. Discord integration

**Status:** Delivered.

The bot handles:

- Prefix commands: `!status`, `!logs`, `!metrics`, `!health`, `!ask`, `!incident`, `!scenario`, `!ack`, `!resolve`, `!watching`
- Conversational replies via @mention using the same agentic loop
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
| Discord bot interface | Delivered | Prefix commands, @mention replies, channel-specific outputs |
| Agent backend and tooling | Delivered | Read-only Prometheus/Loki/HTTP tools; read/write Docker/SSH tools library-only |
| Self-hosted LLM integration | Delivered | OpenAI-compatible endpoint; tool-calling models preferred, graceful fallback otherwise |
| Monitoring and logging integration | Delivered | Prometheus + Loki sources with fallback stubs and optional bearer auth |
| Technical documentation | Delivered | Lives in `docs/` and this README |
| Final demonstration | Pending | Scheduled end-of-internship demo using real or scenario-driven cases |

## What Changed Since the Original Charter

- **Read-only MVP first.** Mutation actions (restart services, change configurations) were deferred to a later phase with human approval rather than being built into the MVP.
- **Stub service status.** A real service registry / orchestrator integration was deferred; `!status` intentionally returns `unknown` until that integration lands.
- **Agentic loop over static reports.** The LLM now writes its own PromQL/LogQL during investigations instead of relying only on pre-composed summaries.
- **Background monitoring inside the bot.** HTTP and Docker endpoint polling plus PromQL alert evaluation run in the Discord bot process rather than requiring a separate monitor.
- **SQLite over a larger database.** Single-node SQLite is sufficient for the MVP and reduces deployment surface.

## Remaining Work and Future Extensions

- Wire `!status` to a real service inventory (Docker, systemd, or orchestrator API).
- Add a multi-environment source registry (prod / staging monitoring sources).
- Implement human-in-the-loop approval before any Docker/SSH write action is executed.
- Persist monitor/alert state so de-duplication survives restarts.
- Add slash commands with autocomplete.
- Introduce RBAC for command channels and sensitive tools.
