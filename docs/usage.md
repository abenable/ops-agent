# Usage

All interaction happens in Discord. Type `/` in a channel the bot can see to
browse the commands, or @mention / DM the bot with a plain question.

## Commands

| Command | Description |
| --- | --- |
| `/status` | LLM-cleaned summary of container + endpoint health |
| `/investigate <question>` | Free-form agentic investigation using read-only tools |
| `/report <service>` | Structured incident report for one service |
| `/containers [raw]` | List Docker containers grouped by state |
| `/watching` | List endpoints configured for background monitoring |
| `/watch <container>` | Add a container to the watch list (status updates + down-alerts) |
| `/unwatch <container>` | Remove a container from the watch list |
| `/watchlist` | List the containers currently being watched |
| `/project-notes` | Post/refresh the project-notes embed |
| `/info` | Bot info and support links |

## Worked examples

**Is everything up?**

```
/status
```

The bot lists containers grouped by state plus the configured endpoints, then
the LLM compresses it into a short health summary. Use `/containers raw:true`
for the unprocessed list.

**Why is a service misbehaving?**

```
/investigate why is marconi-agent-loki restarting?
```

or just `@Oracle why is loki restarting?` in a channel. The model discovers
the exact container name, checks its state, pulls recent logs from Loki (or
Docker), looks at metrics if relevant, and answers with a likely cause and
recommended next steps.

**Formal incident summary for the record:**

```
/report marconi-agent-loki
```

Same machinery, fixed structure: Summary → What happened → Evidence → Likely
cause → Recommended next steps.

**Watch a container so you get told when it dies:**

```
/watch prometheus
```

With `DOCKER_MONITOR=true` and an alerts channel configured, the monitor loop
posts a critical embed to `#alerts` on a running→down transition and a
recovery note to `#status-updates` when it comes back.

## Notes

- Verbose commands (`/containers`) accept a `raw` option to skip the LLM
  summary.
- Answers longer than Discord's 2000-character limit are split into multiple
  messages.
- Service names are matched separator-agnostically: `agent_api`,
  `agent-api`, and `agentapi` all find `marconi-agent-api`.
