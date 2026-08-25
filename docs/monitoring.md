# Monitoring, alerts, and digests

Two background jobs start with the bot: a poller that watches infrastructure,
and a scheduler that posts summaries.

## The monitor

`agent/bot/monitor.py` runs every `MONITOR_INTERVAL_SECONDS` (floored at 10s)
and does two independent passes.

### Containers

Enabled by `DOCKER_MONITOR=true`. Each cycle it lists containers and compares
each one's state to what it saw last time.

Scope is containers whose name contains `DOCKER_NAME_FILTER`, plus anything
explicitly on the watch list. An empty filter means every container. State for
anything that falls out of scope gets pruned.

What fires an alert is a transition, not a state. The first time a container is
seen, its state is recorded and nothing is sent. Only a change fires:

| Transition | Result |
|---|---|
| `running` → anything else | Critical alert to `DISCORD_ALERT_CHANNEL_ID`, `down` recorded in the event log |
| not running → `running` | Recovery notice to `DISCORD_STATUS_CHANNEL_ID`, `up` recorded |

Baselining on first sight is deliberate: a container that is already down when
the bot starts is not a new event, and alerting on it would mean a false alarm
on every restart.

### Endpoints

`MONITORED_ENDPOINTS` is a comma-separated list of `name=url` pairs:

```
MONITORED_ENDPOINTS=prometheus=http://localhost:9090/-/healthy,loki=http://localhost:3100/ready
```

Each is probed every cycle. Anything below a 4xx counts as up; a 4xx, 5xx, or a
connection failure counts as down. The same baseline-then-edge rule applies, to
the same two channels. Malformed entries are skipped.

## The watch list

`/watch <container>` adds a container to `watched_containers` in `data/agent.db`.
Watched containers are always in monitoring scope whatever `DOCKER_NAME_FILTER`
says, which is the point of the list. `/unwatch` removes, `/watchlist` shows.

Names are stored as their real Docker names; lookups are separator-agnostic, so
`/unwatch agent_api` removes `marconi-agent-api`.

## The event log

Every transition is written to the `events` table whether or not an alert
channel is configured. The digests read it, so the log has to exist even when
nobody is being paged. It gets trimmed on write to 90 days, so a crash-looping
container cannot grow it without bound.

## Scheduled digests

`agent/bot/digest.py` fires once a day at `REPORT_HOUR_UTC` and posts to
`DISCORD_REPORTS_CHANNEL_ID`. Unset that channel and both digests are disabled.

The daily digest gives current state, then every transition in the last 24
hours, or `- no changes`.

The weekly one also posts on `WEEKLY_REPORT_WEEKDAY`. It covers
`DIGEST_LOOKBACK_DAYS` and pairs `down` and `up` events into per-target outage
counts and total downtime:

```
- `marconi-agent-loki` — down 3×, total 2h45m
- `marconi-agent-api` — down 1×, total 18m, still down
```

An outage with no matching recovery counts as still down, measured to now.

The weekly digest also explains flapping. Any target that went down twice or
more gets handed to the agent, which investigates it with the same tools it uses
for `/investigate` and adds a **Why** section. A template can count restarts,
but only the agent can read the logs and say what caused them.

Both digests are passed through the summarizer before posting, so what lands in
Discord is prose rather than a raw list. Long reports are chunked to fit
Discord's embed limit; in a forum channel the whole digest becomes one thread.

Render either on demand with `/digest daily` or `/digest weekly`.

## Log forwarding

Setting `DISCORD_LOG_CHANNEL_ID` mirrors INFO-and-above logs into a channel,
which makes tool calls visible live during a demo. `discord.*` loggers are
excluded and `httpx`/`httpx2` are quieted to WARNING, since one INFO line per
HTTP request would flood the channel.
