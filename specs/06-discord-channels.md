# 06 — Discord Channel Implementation Spec

How to make each channel on the server actually carry the traffic its description
promises. Ordered by value-for-effort. Everything reuses code that already exists
(`send_alert`, `check_endpoint`, `run_incident_workflow`, the settings object) — no new
dependencies; `discord.py` already ships everything needed (`Embed`, `tasks.loop`,
`create_thread`, and it plugs into stdlib `logging`).

## Prerequisite: config for channel ids

`settings.py` already has `discord_alert_channel_id` and `discord_guild_id`. Add the rest as
optional ints (all default `None` → feature simply stays off when unset):

```python
discord_incident_channel_id: int | None = None
discord_status_channel_id:   int | None = None
discord_log_channel_id:      int | None = None
# comma-separated list of "name=url" the monitor polls; empty = monitor disabled
monitored_endpoints: str = ""
monitor_interval_seconds: int = 60
```

Mirror them in `.env.example`. Copy each channel's id from Discord (Developer Mode → right
click → Copy ID).

---

## Tier 1 — cheap, high demo value

### #alerts (finish what's started)

**State:** `send_alert(channel_id, message, bot)` exists and `!incident` already posts to
`discord_alert_channel_id`. Only missing: severity + formatting.

**Do:** add an embed-based variant next to `send_alert` in `alerting/discord.py`:

```python
_COLORS = {"info": 0x3498DB, "warning": 0xE67E22, "critical": 0xE74C3C}

async def send_alert(channel_id, message, bot, *, severity="info", title="Alert"):
    channel = bot.get_channel(channel_id)
    if channel is None:
        raise RuntimeError(f"Channel {channel_id} not found")
    embed = discord.Embed(title=title, description=message, color=_COLORS[severity])
    await channel.send(embed=embed)
```

Keeps the same signature plus keyword-only extras, so the existing `!incident` call still
works. **Effort: ~15 min.**

### #test-scenarios (wire the yml files that already exist)

**State:** `scenarios/*.yml` exist but nothing loads them.

**Do:** one command that reads a scenario and runs the incident workflow against its
`service`, so the demo is reproducible:

```python
@bot.command(name="scenario")
async def scenario(ctx, name: str):
    import yaml  # pyyaml is already pulled in transitively; else add it
    path = Path("scenarios") / f"{name}.yml"
    if not path.exists():
        await ctx.send(f"No scenario '{name}'"); return
    data = yaml.safe_load(path.read_text())
    await ctx.send(f"▶️ Simulating: {data['name']} — {data.get('symptom','')}")
    result = await run_incident_workflow(data["service"])
    await ctx.send(result["summary"])
```

Restrict this command to the #test-scenarios channel with a `ctx.channel.id` check.
**Effort: ~30 min** (confirm `pyyaml` is available first; the scenario files imply it).

### #agent-commands (already works — optionally upgrade)

**State:** functional today with `!status !logs !metrics !incident !health`.
**Optional:** register slash-command mirrors via `discord.app_commands` + `bot.tree.sync()`
so users get autocomplete. Nice-to-have, not required for the MVP — the prefix commands
satisfy the "command handling" deliverable. **Effort if wanted: ~1–2 h.**

---

## Tier 2 — the monitoring loop (unlocks two channels at once)

`#alerts` (automated) and `#status-updates` both need the same missing piece: a **background
poller**. Build it once. `discord.py` provides `discord.ext.tasks.loop` — no scheduler
dependency.

**New file `bot/monitor.py`:**

```python
from discord.ext import tasks
from agent.tools.health import check_endpoint
from agent.alerting.discord import send_alert
from agent.config.settings import settings

_last_state: dict[str, bool] = {}   # url -> reachable  (in-memory; fine for MVP)

def _endpoints() -> dict[str, str]:
    out = {}
    for pair in settings.monitored_endpoints.split(","):
        if "=" in pair:
            name, url = pair.split("=", 1)
            out[name.strip()] = url.strip()
    return out

def start_monitor(bot):
    @tasks.loop(seconds=settings.monitor_interval_seconds)
    async def _poll():
        for name, url in _endpoints().items():
            res = await check_endpoint(url)
            up = res["reachable"] and (res["status_code"] or 500) < 500
            prev = _last_state.get(url)

            # #status-updates: post every observed transition (lower noise threshold)
            if prev is not None and prev != up and settings.discord_status_channel_id:
                await send_alert(settings.discord_status_channel_id,
                                 f"{name} is now {'UP' if up else 'DOWN'}", bot,
                                 severity="info", title="Status change")

            # #alerts: only escalate on a healthy→down transition
            if prev is True and not up and settings.discord_alert_channel_id:
                await send_alert(settings.discord_alert_channel_id,
                                 f"{name} ({url}) is unreachable", bot,
                                 severity="critical", title="Service down")
            _last_state[url] = up
    _poll.start()
```

Call `start_monitor(bot)` from `on_ready` in `bot/client.py`.

- **#status-updates** = every up↔down transition (chatty, health pulse).
- **#alerts** = only healthy→down escalations (quiet, actionable).
- `ponytail:` in-memory `_last_state` resets on restart — fine for an MVP; persist to the
  SQLite store if alert de-dup must survive restarts.
- **ponytail:** scope the poller to HTTP endpoints via the existing `check_endpoint`. Don't
  build a generic metrics-threshold engine until a scenario needs it.

**Effort: ~2–3 h** including config + testing with a fake endpoint that toggles.

---

## Tier 3 — richer, only if the rubric asks

### #incidents (thread per incident)

**State:** incidents persist to SQLite; no Discord threads.

**Do:** when `!incident` (or the monitor) escalates, open a thread in the incidents channel
and post the summary there instead of a flat message:

```python
channel = bot.get_channel(settings.discord_incident_channel_id)
thread = await channel.create_thread(
    name=f"{service} — {result['incident_id']}",
    type=discord.ChannelType.public_thread,
)
await thread.send(result["summary"])
```

Store `thread.id` alongside the incident (add a nullable `thread_id` column) so later updates
(`!ack`, `!resolve`) can post back into the same thread. **Effort: ~2–3 h** incl. the schema
add and follow-up posting. Skip unless threaded incident tracking is a graded feature.

### #agent-logs (bot logs → Discord)

**State:** bot logs to stdout via `print`.

**Do:** a `logging.Handler` that forwards records to a channel. Logging is **sync** and the
send is **async**, so buffer through a queue rather than calling `await` from `emit`:

```python
class DiscordLogHandler(logging.Handler):
    def __init__(self, bot, channel_id):
        super().__init__(level=logging.WARNING)   # WARNING+ only, avoid spam/loops
        self.bot, self.channel_id, self.queue = bot, channel_id, asyncio.Queue()
    def emit(self, record):
        self.queue.put_nowait(self.format(record))
    async def pump(self):
        ch = self.bot.get_channel(self.channel_id)
        while True:
            await ch.send(f"```{await self.queue.get()}```")
```

Start `pump()` as a task in `on_ready`; attach the handler to the root logger. Replace the
`print` in `on_ready` with `logging`. **Guardrail:** never route `discord.py`'s own HTTP
logger through this, or an errored send logs an error that tries to send → loop. Keep it at
WARNING+ and exclude the `discord` logger. **Effort: ~2–3 h.** Lowest demo value — a plain
stdout/file log is usually enough; do this only if "logs visible in Discord" is explicitly
wanted.

### #welcome / #project-notes

Human-authored. No code. Leave as-is.

---

## Suggested order

1. #alerts embed + severity (15 min) and #test-scenarios command (30 min) — immediate demo wins.
2. The monitoring loop → lights up automated #alerts **and** #status-updates together (2–3 h).
3. #incidents threads / #agent-logs handler — only if graded.

Total for a convincing MVP demo: **Tier 1 + Tier 2 ≈ half a day.** Tier 3 is optional polish.
