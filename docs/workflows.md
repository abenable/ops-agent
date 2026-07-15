# Workflows

## Incident investigation workflow

1. Collect service status
2. Collect recent metrics
3. Collect recent logs
4. Build a prompt and invoke the self-hosted LLM
5. Persist the summary to SQLite
6. (Optional) Send a Discord alert

## Reporting workflow

1. Look up the incident by id in SQLite
2. Return a formatted report string

## Extending workflows

Replace the stub implementations in `agent.tools` with real calls to your monitoring stack, then update `agent.workflows.incident` to include new signal sources.
