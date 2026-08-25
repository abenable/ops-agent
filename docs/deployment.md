# Deployment

## Docker Compose

```bash
cp .env.example .env      # set DISCORD_BOT_TOKEN and your LLM settings
docker compose up -d
docker compose logs -f bot
```

One service comes up: `bot`, named `marconi-agent-bot`, built from the local
`Dockerfile`.

Prometheus and Loki are not part of this stack. The agent queries whatever
metrics and log servers already exist in your environment, addressed by
`PROMETHEUS_URL` and `LOKI_URL`. With either unset, the corresponding tools are
unavailable and the agent works from the remaining backends.

### Networking

The bot runs `network_mode: host`, so it reaches Prometheus, Loki, the Docker
daemon and the LLM endpoint wherever they run, with no ports to publish and no
service names to resolve. Addresses that work from a shell on the host work
unchanged from inside the container.

`MONITORED_ENDPOINTS` comes from `.env` along with everything else. Its values
are whatever the host can reach:

```
MONITORED_ENDPOINTS=prometheus=http://localhost:9090/-/healthy,loki=http://localhost:3100/ready
```

### The Docker socket

`/var/run/docker.sock` is mounted into the container so the Docker tools see
host containers.

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

To run outside a container at all:

```bash
uv sync
uv run agent bot          # or: uv run python -m agent bot
```

The same environment variables apply, so `PROMETHEUS_URL`, `LOKI_URL`, and
`DOCKER_HOST` point at the same places either way.

## Persistence

**Persist `./data`.** It holds two SQLite files:

| File | Losing it means |
|---|---|
| `agent.db` | The watch list and the transition history behind the digests are gone. |
| `memory.db` | Every channel's conversation context is gone; the bot answers fresh. |

Compose mounts `./data:/app/data`. Nothing else in this stack is stateful.

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
docker compose ps                        # bot up?
docker compose logs -f bot               # bot logs
curl -s "$PROMETHEUS_URL/-/healthy"      # metrics server, wherever it runs
curl -s "$LOKI_URL/ready"                # log server
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
