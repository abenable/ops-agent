# Discord channels

The bot maps its output to purpose-specific channels. Every channel is **optional** — a
feature is simply inactive when its channel id is unset, so you can adopt them incrementally.
Set the ids in `.env` (see [setup.md](setup.md) for how to copy a channel id).

| Channel | Env var | What appears here | Who posts |
| --- | --- | --- | --- |
| `#agent-commands` | — | Operators run `/` commands; the bot replies inline | humans ↔ bot |
| `#alerts` | `DISCORD_ALERT_CHANNEL_ID` | Severity-colored embeds: down-alerts and incident notifications | bot |
| `#status-updates` | `DISCORD_STATUS_CHANNEL_ID` | Every up/down transition + periodic snapshot for **watched** containers | bot |
| `#incidents` | `DISCORD_INCIDENT_CHANNEL_ID` | One thread per incident, with ack/resolve/remediation updates | bot |
| `#agent-logs` | `DISCORD_LOG_CHANNEL_ID` | WARNING+ bot/backend log records | bot |
| `#test-tasks` | `DISCORD_TEST_TASKS_CHANNEL_ID` | `/task` runs (command is restricted to this channel when set) | humans ↔ bot |
| `#welcome`, `#project-notes` | — | Human-authored docs and notes | humans |

## Behavior notes

- **#alerts vs #status-updates:** the status channel is chatty (every transition, `info`
  severity); the alerts channel is quiet and actionable (only healthy→down escalations,
  `critical` severity). Container down-alerts from the watch list (when `DOCKER_MONITOR=true`)
  also post here.
- **#incidents:** threads are created by `/incident` and by monitor escalations. `/ack`,
  `/resolve`, `/approve`, and `/reject` post a follow-up into the incident's thread when one
  exists. Remediation proposals appear here with Approve/Reject buttons.
- **#agent-logs:** only records at `WARNING` and above are forwarded; `discord.py`'s own logs
  are excluded to avoid feedback loops. Leave `DISCORD_LOG_CHANNEL_ID` unset to keep logs on
  stdout only.
- **#test-tasks:** if `DISCORD_TEST_TASKS_CHANNEL_ID` is set, `/task` refuses to
  run elsewhere. Task files live in `tasks/*.yml`.

## Minimum useful setup

For a demo, the two highest-value channels are `#alerts` (so incidents surface) and
`#test-tasks` (to trigger a reproducible run). The rest can be added as needed.
