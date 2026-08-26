# Usage

## Just talk to it

DM the bot, or `@mention` it in any channel it can see:

```
@oracle why is the api container restarting?
```

It investigates and replies with what it found. Follow-ups work, because each
channel and DM is its own conversation thread, so `why?` after an answer refers
to that answer. A different channel starts clean.

An empty mention gets a prompt rather than an investigation. A failure gets an
error message: the bot never goes silent.

## Slash commands

| Command | What it does |
|---|---|
| `/investigate <question>` | Free-form investigation, same as mentioning it. Keyed to the channel, so it joins the conversation. |
| `/status` | Current container and endpoint health, summarized. |
| `/report <service>` | Structured incident report for one service: summary, what happened, evidence, likely cause, next steps. One-shot, so it does not join the channel conversation. |
| `/digest [daily\|weekly] [post_to_reports]` | Render the scheduled report now. Previews in place by default; `post_to_reports:true` sends it to the reports channel. |
| `/containers` | Docker containers grouped by status. |
| `/watching` | HTTP endpoints the monitor polls. |
| `/watch <container>` | Add a container to the watch list. |
| `/unwatch <container>` | Remove one. |
| `/watchlist` | What is on the watch list. |
| `/help` | The list above, in Discord. |

Container and service names are matched loosely, so `agent_api`, `agent-api`,
and `AGENT.API` all find `marconi-agent-api`. A partial name matching more than
one container comes back as ambiguous, listing the candidates instead of
picking one.

Slash commands appear instantly when `DISCORD_GUILD_ID` is set; globally synced
commands can take up to an hour to show up.

## What an investigation looks like

The agent starts from discovery and works toward evidence:

```
tool call: list_services()
tool call: docker_status(container="marconi-agent-loki")
tool call: query_loki_range(logql='{container="marconi-agent-loki"}', minutes=30)

**What happened** — `marconi-agent-loki` exited 4 minutes ago...
**Evidence** — `level=error msg="failed to flush chunks"` ×17
**Likely cause** — the chunk directory is full.
**Next steps** — free space on the Loki volume, then restart the container.
```

It answers in Discord markdown: bold section headers, bullets, and backticks
around names and values. Headings and tables get normalized on the way out,
because Discord renders neither.

## Limits worth knowing

It cannot change anything. Every tool is a read, so it will recommend a restart
but cannot perform one.

A run has a tool budget, `MAX_TOOL_STEPS`, which defaults to 10 tool calls.
Hitting it ends the run with an explanation instead of looping.

Memory is per channel with no cross-thread recall, so it does not know what you
asked it somewhere else. Long answers get split across messages at Discord's
length limit, preferring line breaks.

Prometheus and Loki are optional. With their URLs unset those tools become
unavailable, and the agent works from Docker alone.

## When it runs on its own

Alerts, recovery notices, two-hourly status snapshots, and daily/weekly digests
are covered in [monitoring.md](monitoring.md).
