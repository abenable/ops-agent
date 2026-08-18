# Monitoring, alerts and digests

Two background tasks run inside the Discord client. `start_monitor(bot)` polls
container and endpoint state on an interval and alerts on transitions.
`start_digests(bot)` fires once a day and posts a rendered report. Both are
started from `on_ready` in `src/agent/bot/client.py`, behind a module-level
`_setup_done` flag so a gateway reconnect does not start a second copy of either.

## The monitor loop

`start_monitor()` in `src/agent/bot/monitor.py` builds and starts one task:

```python
@tasks.loop(seconds=max(settings.monitor_interval_seconds, 10))
async def _poll():
    await _poll_containers(bot)
    await _poll_endpoints(bot)
```

`MONITOR_INTERVAL_SECONDS` defaults to 60 and is floored at 10, so a
misconfigured `0` or `1` cannot turn the loop into a busy spin against the Docker
socket and every configured URL. The interval is read when the decorator is
evaluated, which is when `start_monitor()` runs, so changing it takes a restart.

The two polls run in sequence, not concurrently. Endpoint probes have a 10 second
timeout each, so a cycle with several dead endpoints can take longer than the
interval; `tasks.loop` waits for the coroutine to finish before scheduling the
next tick, so cycles skew rather than overlap.

### Container scope

`_poll_containers` returns immediately unless `DOCKER_MONITOR` is true (the
default is false). When it is on, it lists all containers, including stopped
ones, and filters with:

```python
def in_scope(name: str, watched: set[str]) -> bool:
    name_filter = settings.docker_name_filter.lower()
    return (not name_filter) or (name_filter in name.lower()) or (name in watched)
```

Three cases:

- `DOCKER_NAME_FILTER` unset or empty: every container on the host is in scope.
- `DOCKER_NAME_FILTER=marconi`: a container is in scope if `marconi` appears
  anywhere in its lowercased name.
- Regardless of the filter, a container is in scope if its name is on the
  `/watch` list, which is read fresh from `watched_containers` every cycle.

The watch-list check is exact string equality, not the separator-agnostic match
used elsewhere. That is safe because `/watch` resolves the operator's input
through `docker.resolve_container_name()` and stores the exact container name
(`src/agent/bot/slash.py`), so what is in the table is always a real name.

One poll failure does not kill the loop: the `list_containers` call is wrapped in
a bare `except Exception: return`, and `list_containers` itself already returns
`[]` when the socket is missing.

### Why containers are polled over the Docker socket, not PromQL

The obvious alternative is an alerting rule over `up` or a cAdvisor metric. This
reads the Engine API directly instead, for two reasons stated in the function's
docstring.

There is no scrape gap. Prometheus sees container state at its scrape interval,
through an exporter, after that exporter has itself noticed the change; the
socket answers with the state as of the moment of the request. A container that
dies and is restarted by `restart: unless-stopped` between two scrapes can be
invisible to PromQL and is still caught here if it is down at poll time.

There is no PromQL edge that mis-fires on Prometheus itself. Any expression built
on `up`, `absent()` or a `_over_time` window changes value when Prometheus
restarts, when a target is relabelled away, or when the exporter (not the
service) fails. Each of those looks identical to an outage in the query result.
Reading the socket means a container is down when Docker says it is not running,
and nothing else can produce that answer. Prometheus stays in the stack for
metrics, which is what the investigation tools use it for.

### Transitions

State is compared against the previous cycle's value, per target. Only the two
edges alert:

| Edge | Recorded | Channel | Severity | Title |
| --- | --- | --- | --- | --- |
| container `running` to anything else | `('container', 'down')` | `DISCORD_ALERT_CHANNEL_ID` | critical | Container down |
| container not-running to `running` | `('container', 'up')` | `DISCORD_STATUS_CHANNEL_ID` | info | Container up |
| endpoint up to down | `('endpoint', 'down')` | `DISCORD_ALERT_CHANNEL_ID` | critical | Endpoint down |
| endpoint down to up | `('endpoint', 'up')` | `DISCORD_STATUS_CHANNEL_ID` | info | Endpoint up |

Steady state, in either direction, produces nothing: no event row, no message. A
container that stays `exited` for a week is reported once, at the moment it
exited, and afterwards only by the digest snapshot.

The event row is written before the channel check, so transitions are recorded in
the database even when the corresponding channel id is unset. Configuring no
alert channel silences Discord, not the history the digests are built from.

The first observation of a target only baselines it. In `_poll_containers` the
down edge requires `prev == "running"` and the up edge requires
`prev is not None`; in `_poll_endpoints` the check is explicit:

```python
prev = _endpoint_state.get(name)
_endpoint_state[name] = up
if prev is None or prev == up:
    continue
```

With no previous value there is no transition to report, only a state to record.
Without this, every bot restart would alert on every container that happens to be
stopped and every endpoint that happens to be down, which is exactly the noise
that trains people to ignore the alert channel. The cost is that a container
which goes down while the bot is offline produces no alert and no event: the bot
comes back, sees `exited`, and treats that as the baseline. The digest snapshot
still shows it, marked with a warning sign.

State for targets that disappear is pruned. A container not seen this cycle,
because it was removed or because it fell out of scope, is deleted from
`_container_state`; an endpoint no longer in `MONITORED_ENDPOINTS` is deleted from
`_endpoint_state`. A target that returns is baselined again rather than compared
against a stale value from before it left.

### Endpoint probing

```python
async def probe(url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(url)
        return response.status_code < 400
    except (httpx.HTTPError, OSError):
        return False
```

Up means one GET, redirects followed, returning a status below 400. Down means
anything else: a 4xx or 5xx status, a connection refused, a DNS failure, a TLS
error, or the 10 second timeout expiring. There is no retry and no consecutive
failure count, so a single dropped request produces an alert and the next
successful cycle produces a recovery. At a 60 second interval that is a
tolerable amount of flap for a lab, and the weekly digest counts outages, so a
target that does this repeatedly shows up as flapping and gets investigated.

Endpoints are what the Docker poll cannot see. The container poll knows only
about containers on the host whose socket is mounted, and only about whether the
process is running. An endpoint entry (`name=url` pairs in `MONITORED_ENDPOINTS`)
covers a service on another machine, a service behind a reverse proxy where the
proxy is the thing that breaks, a non-containerised service, and the case where
the container is running fine but the application inside it stopped answering.
The two checks answer different questions: "is it running" and "does it respond".

## The event log

`src/agent/watchlist/repository.py` holds both tables in the single SQLite file
resolved by `DB_PATH` in `src/agent/config/settings.py` (default `data/agent.db`,
the same file as the conversation checkpoints).

```sql
CREATE TABLE IF NOT EXISTS events (
    target TEXT NOT NULL,
    kind   TEXT NOT NULL,
    state  TEXT NOT NULL,
    at     TEXT NOT NULL
)
```

`target` is a container name or an endpoint name, `kind` is `container` or
`endpoint`, `state` is `down` or `up`, and `at` comes from SQLite's
`datetime('now')`, which is UTC in `YYYY-MM-DD HH:MM:SS`. The fixed-width format
sorts and compares lexicographically, which is why `events_since()` can filter
with a plain string comparison and `ORDER BY at`. There is no primary key and no
index: this table holds transitions for a handful of targets over 90 days, and
the only query is a range scan over the whole thing.

`init_db()` is called at the top of every public function, so no caller has to
remember to initialise the database and a deleted file is recreated on next use.

Every `record_event` trims in the same transaction as the insert:

```sql
DELETE FROM events WHERE at < datetime('now', '-90 days')
```

Trimming on write means there is no separate cleanup task to schedule, monitor or
forget about. It matters because transitions are usually rare but need not be: a
container in a crash loop can produce one event per poll cycle, up to one every
10 seconds, indefinitely. Bounding the table by time rather than by row count
keeps the digest queries constant-cost, and 90 days comfortably covers the
7 day default weekly lookback.

Live state lives only in the two module-level dicts in `monitor.py`,
`_container_state` and `_endpoint_state`. They are lost on restart, which is what
makes the baseline rule necessary. The durable record is this table, and it is
the only thing the digests read for history.

## Digests

`start_digests()` in `src/agent/bot/digest.py` starts one task, not two:

```python
@tasks.loop(time=time(hour=settings.report_hour_utc, tzinfo=UTC))
async def _digest():
    await run_tick(bot)
```

`run_tick` always posts the daily digest, and additionally posts the weekly when
`now.weekday() == settings.weekly_report_weekday` (`WEEKLY_REPORT_WEEKDAY`,
0 = Monday). One task with a weekday check is simpler than two schedules, and it
guarantees that on report day the weekly follows the daily in the channel rather
than racing it.

`tasks.loop(time=...)` has no missed-tick catch-up. A bot that is down or
restarting at `REPORT_HOUR_UTC` skips that firing entirely; it does not post late
when it comes back. That is the behaviour worth having: a "daily report" that
arrives seven hours after the hour it names, next to a normal one, is worse than
a gap, and the events it would cover are still in the table for the weekly
roll-up.

Both digests are disabled by leaving `DISCORD_REPORTS_CHANNEL_ID` unset. The
check is at the top of `post()`, before any rendering, and logs at INFO rather
than warning: an unset reports channel is a configuration choice, not a fault.

`/digest [daily|weekly] [post_to_reports]` renders the same functions on demand.

### What is in them

Both start from `_snapshot()`, the current state of everything in scope:

- `**Containers** (n)`, one line per container sorted by name, with its Docker
  `State`, a warning sign when it is not `running`, and the human `Status` string
  (`Up 3 days`, `Exited (1) 4 minutes ago`).
- `**Endpoints** (n)`, one line per configured endpoint, each probed live at
  render time, marked reachable or unreachable.

`_containers()` applies the same `in_scope()` rule the monitor alerts on, so a
digest never lists something the alerts would have ignored. Note that it is not
gated on `DOCKER_MONITOR`: with the flag off, digests still show container state
but the transition sections stay empty, because nothing ever records a container
event.

The daily adds every transition in the last 24 hours, oldest first, one line
each, in the form `- 03:12 marconi-agent-api down` (with the target name in
backticks), or `- no changes`.

The weekly adds per-target totals over `DIGEST_LOOKBACK_DAYS` (default 7):

```
- `marconi-agent-api` — down 3×, total 1h07m, still down
```

and then, when anything flapped, a `**Why**` section.

### Details and Summary

Every digest body is wrapped by `_with_summary()`:

```python
return f"**Summary**\n{summary}\n\n**Details**\n{body}"
```

The **Details** half is `body`, rendered from the monitor's own data by the
functions above, and passed through unmodified. The model never sees it as
something to rewrite. The numbers are already exact, so a paraphrase has nothing
to add and two ways to lose: dropping a target, or inventing a figure that reads
as authoritative. If you need to know what actually happened, read Details.

The **Summary** half is generated on top, by `clean()` from
`src/agent/bot/summarize.py`, asking for a 2 to 3 sentence natural-language
summary highlighting anything noteworthy. It is capped at 1900 characters, and if
the LLM is unreachable or returns nothing, `clean()` falls back to a code block
of the raw body, so a dead LLM endpoint costs the prose and not the report.

The single exception, where model output lands inside Details, is the weekly
**Why** section. Everything else in the report can be computed from the events
table; "why did this keep failing" cannot. A target with at least `_FLAP_THRESHOLD`
(2) outages in the lookback window counts as flapping, and every flapping target
is handed to `_explain()`, which asks the full investigation agent to go and read
that target's logs and metrics:

> These targets went down repeatedly in the last {days} days: {names}. Check
> their logs and metrics and give one short paragraph on the likely cause and
> what an operator should do.

That runs the same tool loop a `/investigate` would, one-shot with no thread id.
A failure is caught, logged at warning level, and rendered inline as
`(could not investigate ...)`, so a narrative that fails never costs the report
it was attached to.

### Downtime pairing

`_downtime()` walks the window's events in time order and pairs them per target:

- A `down` opens an outage: increment the target's count, remember the timestamp.
  A second `down` while one is already open is ignored, so a duplicate cannot
  inflate the count.
- An `up` closes the open outage and adds `up_time - down_time` to the total. An
  `up` with nothing open is ignored, which happens when the matching `down` falls
  before the start of the window. Such a target appears with 0 outages and 0
  downtime, correctly reporting that nothing failed inside the window.
- Anything still open when the events run out is not dropped. Its downtime is
  measured to `datetime.now(UTC)` and the entry is flagged `still_down`, which
  renders as a trailing `, still down`.

Measuring the open outage to now is the important half. Discarding an unclosed
`down` would make the currently broken target the one with the least reported
downtime, and a weekly report where the ongoing outage is the least visible line
is worse than no report. `_duration()` formats under an hour as `43m` and above
as `1h07m`.

## Delivery

All Discord output from these loops goes through `src/agent/alerting/discord.py`.

### Severity colours

| Severity | Colour | Used by |
| --- | --- | --- |
| `info` | `0x3498DB` blue | recovery notices, all report embeds |
| `warning` | `0xE67E22` orange | available, not used by the monitor |
| `critical` | `0xE74C3C` red | container down, endpoint down |

An unrecognised severity string falls back to the info colour rather than
raising.

### Channel resolution

```python
channel = bot.get_channel(channel_id)
if channel is not None:
    return channel
return await bot.fetch_channel(channel_id)
```

`get_channel()` is a cache lookup and returns `None` whenever the gateway has not
yet delivered that channel, which is common in the seconds after `on_ready` and
after a reconnect. A first alert that arrives in that window would silently go
nowhere. The cache is tried first because it is free and covers almost every
call; `fetch_channel` is the HTTP round trip that makes the cold path work. A
`DiscordException` from the fetch (bad id, no permission, deleted channel) is
logged as a warning and yields `None`.

### Failures are logged, not raised

`send_alert` and `post_report` both swallow `discord.DiscordException` into a
`logger.warning`. This is deliberate and specific to the caller: these run inside
`tasks.loop` jobs, and an exception escaping a loop iteration stops the task. A
transient 503 from Discord while posting one alert would otherwise end all
monitoring until the process restarts, with no obvious symptom beyond alerts
having quietly stopped. A logged failure loses one message; a raised one loses
the monitor. Log delivery also has its own path to Discord via
`DiscordLogHandler` in `src/agent/bot/client.py`, so the warning is visible.

### Forum versus text channel

`post_report()` takes a list of chunks and posts them as one unit, branching on
the channel type:

- `discord.ForumChannel`: one `create_thread()` with the first chunk as its embed
  and the title as the thread name (truncated to Discord's 100 character limit),
  then the remaining chunks sent as messages inside that thread. The whole report
  is one thread, and discussion of it stays under it.
- Anything else: one embed per chunk, the first carrying the title and the rest
  titled `<title> (cont.)`, sent to the channel directly. A text channel has no
  container to group them into, so the numbering is what ties them together.

Chunking happens in `digest.post()` before the call, at 3900 characters:

```python
chunks = [body[i : i + 3900] for i in range(0, len(body), 3900)] or [body]
```

Discord caps an embed description at 4096; 3900 leaves headroom and the embed
description is truncated to 4096 again on the way out as a backstop. The split is
a hard character slice, so a long report can break mid-line.

### Seeding the thread's memory

`post_report()` returns the id a caller should key conversation memory to: the
new thread's id for a forum channel, `channel_id` itself for a text channel, or
`None` if nothing was posted. `digest.post()` uses it:

```python
thread_id = await discord_alert.post_report(channel_id, title, chunks, bot)
if thread_id is not None:
    await seed(str(thread_id), body)
```

`engine.seed()` writes the full body (not the chunks, and not the title) into
that thread's checkpoint as a `HumanMessage`. The mention handler in
`src/agent/workflows/nl.py` keys conversations by `str(message.channel.id)`, and
a Discord thread is itself a channel, so the id seeded here is the same id a
message posted inside the thread resolves to. The result is that someone can
@mention the bot under a posted report and ask "why was the API down at 03:12"
without pasting anything: the report is already the first turn of that thread's
history.

The returned id is chosen to match that convention on both sides, which is why a
text channel returns its own id rather than `None`. Two caveats: for a text
channel the memory is keyed to the whole channel, so the seeded report is context
for every later mention there, and `memory.window()` trims a thread to
`MAX_CONTEXT_TOKENS`, so in a busy thread the seeded report is the oldest content
and the first to be evicted.
