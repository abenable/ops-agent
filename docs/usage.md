# Using the agent in Discord

The agent answers questions about the lab's containers, metrics and logs. You can
reach it three ways: a slash command, a direct message, or an `@mention` in a channel
it can see. All three end up in the same read-only investigation loop.

## Command reference

| Command | Arguments | What it does | Ephemeral |
| --- | --- | --- | --- |
| `/status` | none | Lists containers grouped by state plus the configured monitored endpoints, then has the model summarize them. | No |
| `/investigate` | `question` (required) | Runs a free-form investigation with every tool available, keeping this channel's conversation context. | No |
| `/report` | `service` (required) | Structured incident report for one service, using a fixed section template. | No |
| `/digest` | `period` (`daily` or `weekly`, default `daily`), `post_to_reports` (boolean, default false) | Renders the scheduled report immediately, either as a reply here or posted to the reports channel. | No |
| `/containers` | none | Lists Docker containers grouped by status, summarized by the model. | Yes |
| `/watching` | none | Lists the HTTP endpoints the background monitor polls. | Yes |
| `/watch` | `container` (required) | Resolves the name against running containers and adds the exact name to the watch list. | Yes |
| `/unwatch` | `container` (required) | Removes a container from the watch list. | Yes |
| `/watchlist` | none | Lists the containers currently on the watch list. | Yes |
| `/reset` | none | Deletes this channel's conversation thread. | Yes |
| `/help` | none | Lists the commands and explains DM/mention use. | Yes |

"Ephemeral" means only you see the reply. `/containers` acknowledges ephemerally; its
"no containers found" reply is explicitly ephemeral, while the summarized listing is
sent as a plain followup (`src/agent/bot/slash.py`).

## The commands in detail

### `/investigate`

The main entry point. Ask a whole question, not a keyword:

```
/investigate why did the loki container stop last night?
```

The agent decides which tools to call. Typically it starts with `list_services` to
learn the real names, checks container state, reads recent logs, then queries
Prometheus or Loki if the logs are not conclusive. The reply comes back as Discord
markdown with bold section headers and bullets, and it ends with a likely cause and
recommended next steps for a human operator. Ambiguity and tool failures are reported
in the answer rather than swallowed: a tool that raises is fed back to the model as
text, so the answer may say a check could not be completed.

The question is echoed above the answer, so a long reply is still readable in
scrollback.

### `/report`

```
/report agent_api
```

Takes one service name and produces a fixed set of sections: **Summary**, **What
happened**, **Evidence**, **Likely cause**, **Recommended next steps**. If the service
looks healthy, the Summary says so and the rest stays short. Unlike `/investigate`,
this is always a one-shot run: it does not read or write the channel's conversation
history, so a report is reproducible and does not push older turns out of memory.

### `/digest`

```
/digest period:weekly
/digest period:daily post_to_reports:true
```

Renders the same report the scheduler posts. The daily digest is the current snapshot
plus every up/down transition in the last 24 hours. The weekly digest is the snapshot
plus, for each target, how many outages it had and how much total downtime it
accumulated over the configured lookback window; an outage with no recovery yet is
measured to now and marked "still down". If a target went down twice or more in the
window, the weekly adds a **Why** section where the agent actually goes and reads that
target's logs and metrics.

The **Details** section of both digests is rendered from the recorded events, so those
numbers are exact. Only the **Summary** at the top and the weekly **Why** paragraph
come from the model.

With `post_to_reports:true` the digest goes to the configured reports channel instead
of being previewed in place, and that thread's memory is seeded with the report body,
so you can `@mention` the bot under the posted report and it already has it as context.

### `/status` and `/containers`

`/status` covers containers and monitored endpoints together; `/containers` covers only
containers and replies privately. Both fetch the raw list and pass it through the model
for a readable summary. If the model is unreachable, you get the raw list in a code
block instead of an error.

### `/watch`, `/unwatch`, `/watchlist`, `/watching`

`/watch` resolves the name you type against the containers Docker knows about (running
or not) and stores the exact container name, so `/watch agent_api` records
`marconi-agent-api`. A watched container is monitored for stop/start transitions even
if it does not match the configured name filter. `/watching` is a different thing: it
lists the HTTP endpoints configured for polling, which are set in the environment and
cannot be changed from Discord.

## Talking to it conversationally

Send it a direct message, or `@mention` it in any channel it can read, and the message
goes through the same loop as `/investigate`. In a guild it only answers when
mentioned; the mention markup is stripped before the question is read, and a mention
with no question gets a prompt back rather than an empty investigation.

Memory is keyed by channel id, and a DM is a channel, so:

- Each channel and each DM has its own separate conversation.
- Follow-up questions work: "why?", "show me the evidence for that", or "check the
  other one too" resolve against the previous turns in that channel.
- Two channels never see each other's history.
- `/reset` clears the history for the channel you run it in.
- History is stored in SQLite and survives a bot restart. A long conversation still
  drops its oldest turns once it outgrows the context budget.

## What it will and will not do

It reads four things:

1. Container state and status from the Docker Engine API.
2. Container stdout/stderr logs directly from Docker.
3. Prometheus metrics, including metric name and label discovery, instant and range
   queries.
4. Loki logs, including label discovery, instant and range queries.

It will not restart a container, edit a config, scale anything, or run a shell command.
This is not a policy the model is asked to follow. It is the shape of the tool surface:
nothing in `src/agent/tools/` exposes a call that changes state, so there is no path
from a model decision to a write. When something needs doing, the answer names the
action for you to take.

Note that the same applies to information it cannot reach. If Prometheus is not
scraping a target, or Promtail is not shipping a container's logs to Loki, the agent
cannot see them and will say so instead of inventing numbers.

## Practical notes

- **Names are matched loosely.** Separators and case are ignored, and a partial name
  matches: `agent_api`, `agent-api` and `agentapi` all find `marconi-agent-api`.
- **Ambiguity is reported, not guessed.** If your partial name matches more than one
  container, you get back the list of candidates and a request to use one of the exact
  names. An exact name always wins over a substring match, so a container literally
  called `agent_api` beats `marconi-agent-api-worker`.
- **Long answers arrive as several messages.** Replies are split at roughly 1900
  characters, preferring line breaks, because Discord caps a message at 2000.
- **A question that runs out of tool budget still answers.** The loop has a fixed step
  budget (`MAX_TOOL_STEPS`). When it is exhausted, the agent gets one last pass with no
  tools and returns a summary of what it found, what it thinks the cause is, and what
  it could not check.
- **Loki labels are not Docker names.** Loki's label schema comes from Promtail's
  scrape config, so there is not always a `container` label. The agent is told to
  discover labels before writing a LogQL selector, which is why an answer may include a
  label-discovery step before the actual log query.

## Troubleshooting

**The bot does not respond to a mention or DM.** Check that the Message Content Intent
is enabled for the application in the Discord developer portal; without it the bot
exits at startup with a log line saying so. Also check the bot can read the channel. A
failure inside the handler always replies with an error message, so complete silence
points at intents, permissions, or the process not running.

**A slash command is missing.** Commands are synced once on startup. With
`DISCORD_GUILD_ID` set, the sync is per guild and is near-instant; without it, the sync
is global and Discord takes time to propagate. Restart the bot after changing the
command set, and check the startup logs for the "Synced N slash command(s)" line or a
sync failure warning.

**No containers are listed.** `/status` and `/containers` say so directly. The Docker
socket is not reachable: either it is not mounted into the container, or `DOCKER_HOST`
points somewhere wrong. An empty `DOCKER_HOST` is treated as unset and falls back to
the local socket.

**Answers are slow or the model does not answer at all.** Each LLM call has a 60 second
timeout, and an investigation makes one call per tool step, so a multi-step
investigation on a small local model takes a while. If the endpoint is down entirely,
`/status` and `/containers` fall back to raw output with the error inline, and an
investigation returns an "Investigation failed" message with the reason. Check
`LLM_BASE_URL` and that the model named in `LLM_MODEL` is actually loaded.
