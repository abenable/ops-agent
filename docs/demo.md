# Demo script

A scripted end-to-end scenario for the final demonstration: a real service
goes down, the bot alerts, the agent investigates, and the recovery is
confirmed — all from Discord.

Prerequisites: the compose stack is up (`docker compose up --build`),
`DOCKER_MONITOR=true`, and `DISCORD_ALERT_CHANNEL_ID` /
`DISCORD_STATUS_CHANNEL_ID` are set. Give the monitor one poll cycle
(`MONITOR_INTERVAL_SECONDS`, default 60s) after startup to baseline state.

## 1. Baseline health

```
/status
```

Shows all containers running (bot, prometheus, loki, promtail, node-exporter,
cadvisor) and the monitored endpoints.

## 2. Break something

```bash
docker stop marconi-agent-loki
```

Within one poll cycle, a critical **Container down** embed lands in `#alerts`.

## 3. Investigate from Discord

```
/investigate why is loki down?
```

The agent checks the container state (`exited`), pulls its recent logs, and
answers with a likely cause and next steps. Then the formal version:

```
/report marconi-agent-loki
```

produces the structured incident report (Summary → What happened → Evidence →
Likely cause → Recommended next steps).

## 4. Recover

```bash
docker start marconi-agent-loki
```

A **Container up** recovery note lands in `#status-updates` within one poll
cycle. Re-run `/status` to show everything green again.

## Regression coverage

This exact path (baseline → stop → critical alert → start → recovery note) is
covered by `test_demo_incident_scenario_end_to_end` in
`tests/test_monitor.py`, which drives the monitor loop with fake Docker
responses — no live stack needed.
