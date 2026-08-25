# Deployment

## Docker Compose

```bash
cp .env.example .env      # set DISCORD_BOT_TOKEN and your LLM settings
docker compose up -d
docker compose logs -f bot
```

Four services come up:

| Service | Container | Purpose |
|---|---|---|
| `bot` | `marconi-agent-bot` | The agent. Built from the local `Dockerfile`. |
| `prometheus` | `marconi-agent-prometheus` | Metrics, on `:9090`. Scrapes itself, node-exporter, cadvisor. |
| `loki` | `marconi-agent-loki` | Logs, on `:3100`. |
| `promtail` | `marconi-agent-promtail` | Ships every container's logs into Loki. |

Prometheus, Loki, and Promtail configs are inlined as Compose `configs`, so
there are no side files to keep in sync.

### Networking

The bot runs `network_mode: host`. It needs to reach Prometheus and Loki on
`localhost`, plus an LLM endpoint that may be anywhere on the network. The
cost is that bridge-networked containers cannot reach the bot by service name,
so they go through `host.docker.internal`, mapped via `extra_hosts`.

That is also why `MONITORED_ENDPOINTS` is set in the Compose file rather than
`.env`: the right values depend on the host networking.

```yaml
MONITORED_ENDPOINTS: "prometheus=http://localhost:9090/-/healthy,loki=http://localhost:3100/ready"
```

### The Docker socket

`/var/run/docker.sock` is mounted into `bot` and `promtail` so the container
tools and log shipping can see host containers.

`:ro` on that mount makes the socket *file* read only. It does not restrict the
Engine API behind it, and socket access is root-equivalent on the host. The
read-only guarantee comes from the tool surface, since `agent/tools/` exposes no
mutating call. It does not come from the flag.

## The image

`Dockerfile` is a single stage on `python:3.13-slim-bookworm` using `uv`.
Dependencies install from `pyproject.toml` + `uv.lock` before the source is
copied, so a code change does not re-resolve the dependency tree.

```
ENTRYPOINT ["uv", "run"]
CMD ["python", "-m", "agent", "bot"]
```

## Without Compose

If Prometheus, Loki, and Docker already exist elsewhere, run the bot alone:

```bash
uv sync
uv run agent bot          # or: uv run python -m agent bot
```

Point `PROMETHEUS_URL`, `LOKI_URL`, and `DOCKER_HOST` at them.

## Persistence

**Persist `./data`.** It holds two SQLite files:

| File | Losing it means |
|---|---|
| `agent.db` | The watch list and the transition history behind the digests are gone. |
| `memory.db` | Every channel's conversation context is gone; the bot answers fresh. |

Compose mounts `./data:/app/data`. Prometheus and Loki keep their own named
volumes (`prom_data`, `loki_data`).

Back up with the bot stopped:

```bash
docker compose stop bot
cp -r data data.bak
docker compose start bot
```

Or live, with SQLite's own backup:

```bash
sqlite3 data/agent.db  ".backup 'backup/agent.db'"
sqlite3 data/memory.db ".backup 'backup/memory.db'"
```

## Discord setup

The bot needs the **Message Content** privileged intent to read mentions and
DMs, plus permission to send messages and use slash commands in the channels it
serves. Set `DISCORD_GUILD_ID` so commands sync to your guild immediately;
without it, global sync can take up to an hour.

## Health checks

```bash
docker compose ps                        # everything up?
docker compose logs -f bot               # bot logs
curl -s localhost:9090/-/healthy         # Prometheus
curl -s localhost:3100/ready             # Loki
```

In Discord, `/status` is the end-to-end check. It lists containers over the
Docker socket, shows the configured endpoints, and summarizes both through the
LLM, so one command exercises Docker access and the model together. Note that
it reports the endpoints the monitor polls without probing them itself.

## Upgrading

```bash
git pull
docker compose build bot
docker compose up -d bot
```

`data/` is untouched, so the watch list and conversation history carry over.
