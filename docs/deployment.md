# Deployment

Two supported ways to run the bot: directly on a host with uv, or as a container
in the compose stack alongside Prometheus, Loki and Promtail. Both read the same
`.env`. See `docs/configuration.md` for what each variable does.

## Prerequisites

- Python 3.13 or newer. `pyproject.toml` sets `requires-python = ">=3.13"` and
  `.python-version` pins 3.13.
- [uv](https://docs.astral.sh/uv/). The lockfile is `uv.lock` and the container
  image installs with `uv sync --frozen`.
- Docker, if you want container status, container logs, container monitoring, or
  the compose stack. The agent talks to the Engine API directly over the socket;
  no Docker SDK is involved.
- A reachable OpenAI-compatible chat completions endpoint (Ollama, vLLM,
  llama.cpp's server, or a proxy such as LiteLLM). Set `LLM_BASE_URL` and
  `LLM_MODEL` to match it.
- A Discord application with a bot user, and the **Message Content** privileged
  intent enabled for it.

The intent is not optional. `run_bot()` sets `intents.message_content = True`,
and if the portal has it switched off, discord.py raises
`PrivilegedIntentsRequired` at login. The bot catches that, logs

```
CRITICAL Privileged 'Message Content Intent' is not enabled for this bot.
Enable it at https://discord.com/developers/applications
```

and exits with status 1. Without it, @mentions and DMs carry no text and the
natural-language handler has nothing to read.

## Discord setup

1. Create an application at <https://discord.com/developers/applications>.
2. Open the **Bot** tab, add a bot user, and copy the token into
   `DISCORD_BOT_TOKEN`. The token is shown once; regenerate it if you lose it.
3. On the same tab, under **Privileged Gateway Intents**, enable **Message
   Content Intent**.
4. Under **OAuth2 > URL Generator**, select the `bot` and
   `applications.commands` scopes. `applications.commands` is what allows slash
   commands to be registered. Grant at least: View Channels, Send Messages,
   Embed Links, Read Message History. Add Create Public Threads if the reports
   channel is a forum channel, since each digest opens a thread there.
5. Open the generated URL and invite the bot to your server.
6. Copy the channel ids you want to use (Developer Mode on, right-click a
   channel, Copy Channel ID) into `DISCORD_ALERT_CHANNEL_ID`,
   `DISCORD_STATUS_CHANNEL_ID`, `DISCORD_REPORTS_CHANNEL_ID` and
   `DISCORD_LOG_CHANNEL_ID`.

### Command sync

Slash commands are registered once per startup, in `on_ready`
(`src/agent/bot/client.py`):

- With `DISCORD_GUILD_ID` set, the global command set is copied to that guild and
  synced there. A guild sync is visible almost immediately, which is what you
  want while developing.
- With it unset, the sync is global. Discord propagates global commands over up
  to an hour, so a fresh command may not appear right away.

Sync failures are logged as a warning and do not stop the bot; existing commands
keep working. `on_ready` is guarded by a module-level flag, so a gateway
reconnect does not repeat the setup.

## Running locally

```bash
git clone <repo> && cd agent
uv sync
cp .env.example .env
$EDITOR .env          # at minimum: DISCORD_BOT_TOKEN, LLM_BASE_URL, LLM_MODEL
uv run python -m agent bot
```

`uv sync` installs the dev group too, so `uv run pytest` works for a quick check
before starting the bot. The default pytest run excludes the integration marker,
so it makes no network calls.

The package also installs an `agent` console script (`project.scripts` in
`pyproject.toml`), so inside the environment `agent bot` is equivalent to
`python -m agent bot`.

`bot` is the only subcommand (`src/agent/cli.py`). Running `agent` with no
subcommand prints help and exits 1. There is no separate worker, migration, or
serve command: the one process runs the Discord client, the monitor loop and the
digest scheduler.

## The image

`Dockerfile`, layer by layer:

```dockerfile
FROM python:3.13-slim-bookworm
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev
ENTRYPOINT ["uv", "run"]
CMD ["python", "-m", "agent", "bot"]
```

- The base is the slim Debian bookworm Python 3.13 image, and uv is installed
  with pip into it.
- Only the project metadata is copied first, then dependencies are installed
  with `--no-install-project`. Editing a source file therefore does not
  invalidate the dependency layer, and a rebuild after a code change reuses the
  cached install. `--frozen` means the resolution comes from `uv.lock` as
  committed, so the image gets exactly the locked versions. `--no-dev` leaves
  pytest and ipykernel out.
- `src` is copied after that, and the second `uv sync` installs the project
  itself into the environment.
- `ENTRYPOINT ["uv", "run"]` means the container command runs inside the synced
  environment; `CMD` supplies the default `python -m agent bot`.

The `COPY` line includes `README.md`, because `pyproject.toml` declares
`readme = "README.md"` and the build backend reads it when installing the
project. **A `README.md` must exist at the repo root or the image build fails**
at that COPY. `.dockerignore` excludes `*.md` but re-includes it with
`!README.md` for the same reason.

`.dockerignore` also excludes `.env`, `data/`, `tests/`, `docs/`, `.git` and the
local `.venv`, so the image carries no secrets and no host database file.

## The compose stack

`docker-compose.yml` defines four services.

| Service | Image | Ports | Volumes |
| --- | --- | --- | --- |
| `bot` | built from this repo | host network | `./data:/app/data`, `/var/run/docker.sock:/var/run/docker.sock:ro` |
| `prometheus` | `prom/prometheus:latest` | `9090:9090` | named volume `prom_data:/prometheus` |
| `loki` | `grafana/loki:latest` | `3100:3100` | named volume `loki_data:/loki` |
| `promtail` | `grafana/promtail:latest` | none | `/var/run/docker.sock:/var/run/docker.sock:ro` |

```bash
cp .env.example .env
$EDITOR .env
docker compose up -d --build
docker compose logs -f bot
```

The `bot` service reads `.env` through `env_file`, and additionally sets
`MONITORED_ENDPOINTS` in its `environment:` block to
`prometheus=http://localhost:9090/-/healthy,loki=http://localhost:3100/ready`.
Compose's `environment:` wins over `env_file:`, so that value overrides whatever
`.env` says. Remove or edit it in the compose file if you want to monitor
something else. `depends_on` only orders startup; it does not wait for
Prometheus or Loki to become ready, which is harmless here because the tools
fail per call rather than at startup.

All three backend configurations are inlined in the top-level `configs:` block
of `docker-compose.yml` and mounted into the containers as files
(`/etc/prometheus/prometheus.yml`, `/etc/loki/local-config.yaml`,
`/etc/promtail/config.yml`). There are no separate config files in the repo to
edit; change the compose file and recreate the service.

`prom_data` and `loki_data` are named Docker volumes, so metric and log history
survives `docker compose down`. They are removed by `docker compose down -v`.

### Host networking

`bot` runs with `network_mode: host`. It needs to reach Prometheus and Loki on
`localhost:9090` and `localhost:3100` as the defaults describe, an LLM endpoint
that usually lives outside the compose network, and the Docker socket to see
containers on the host as the host names them.

The consequence runs the other way: a service on the default bridge network
cannot reach the bot by the service name `bot`, because the bot has no address on
that network. It is reachable through the host gateway instead, which is why the
`prometheus` service declares

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

Use `host.docker.internal` from a bridge-networked container when you need to
reach something the bot exposes on the host. Note also that host networking means
the bot inherits the host's port space; the `9090:9090` and `3100:3100` mappings
belong to the bridge-networked Prometheus and Loki containers, not to the bot.

### Promtail and the log labels

Promtail is the agent that gets container logs into Loki. It has no ports of its
own: it reads from the Docker socket, and pushes to
`http://loki:3100/loki/api/v1/push` over the compose network.

Its single scrape job uses `docker_sd_configs` against
`unix:///var/run/docker.sock` with a 15 second refresh, so containers are picked
up as they appear. Three relabel rules produce the labels you then query in
LogQL:

```yaml
relabel_configs:
  - source_labels: ['__meta_docker_container_label_com_docker_compose_service']
    target_label: 'service'
  - source_labels: ['__meta_docker_container_name']
    regex: '/?(.*)'
    target_label: 'container'
    replacement: '$1'
  - target_label: 'job'
    replacement: 'docker-logs'
```

- `service` comes from the container's `com.docker.compose.service` label, so it
  is the compose service name (`bot`, `prometheus`, `loki`, `promtail`). A
  container not started by compose has no such label and therefore no `service`
  label at all.
- `container` is the Docker container name with the leading `/` stripped by the
  regex capture (`marconi-agent-bot`, not `/marconi-agent-bot`).
- `job` is set to the constant `docker-logs` for everything this Promtail ships.

A LogQL selector therefore looks like `{service="bot"}` or
`{container="marconi-agent-bot"}` or `{job="docker-logs"}`. This is why the Loki
tools tell the model to call `get_loki_label_values` before writing a selector:
the label schema is Promtail's, not Docker's, and a different Promtail
configuration produces entirely different labels.

### Prometheus targets

The inlined `scrape_configs` has three jobs: `prometheus` scraping itself at
`localhost:9090`, `node-exporter` at `node-exporter:9100`, and `cadvisor` at
`cadvisor:8080`.

Only the first one resolves. Neither `node-exporter` nor `cadvisor` is defined as
a service in this compose file, so those two jobs sit permanently in an error
state and no host or per-container metrics are collected. Out of the box, the
only metrics available to `query_prometheus` are Prometheus's own. Add
`prom/node-exporter` and `gcr.io/cadvisor/cadvisor` services to the compose file,
on the same bridge network so the existing target names resolve, if you want CPU,
memory, disk and per-container metrics.

## Security: the Docker socket

Two services mount `/var/run/docker.sock`: `bot` (for container status, logs and
monitoring) and `promtail` (for service discovery). Both mount it `:ro`.

Be clear about what that flag does. `:ro` makes the socket **file** read-only at
the mount. It does not make the Docker Engine API read-only. The API behind the
socket is still fully writable: anything with access to it can create, start,
stop and delete containers, and can start a privileged container that mounts the
host filesystem. Docker socket access is root-equivalent on the host, `:ro` or
not.

The bot is read-only because of what it can do, not where it is mounted. Nothing
in `src/agent/tools/` calls a mutating Engine endpoint: the Docker tools issue
`GET /v1.40/containers/json` and `GET /v1.40/containers/{id}/logs`, and there is
no tool that starts, stops or removes anything. The model cannot invoke a call
that does not exist in its tool set. That is the guarantee; the `:ro` flag is
not.

If that is not enough for your threat model, put a socket proxy that allowlists
GET routes (for example `tecnativa/docker-socket-proxy`) between the socket and
the containers, and point `DOCKER_HOST` at it.

## Operational notes

**Persist `./data`.** It holds `agent.db`, the single SQLite file containing the
watch list, the alert event log, and every conversation checkpoint. The compose
file bind-mounts `./data:/app/data`; without it, the watch list and all thread
memory are lost on every container recreate. The file is excluded from git by
`.gitignore` and from the image by `.dockerignore`. Back it up with a plain file
copy while the bot is stopped, or with `sqlite3 data/agent.db ".backup ..."`
while it is running.

**Restart policy.** All four services use `restart: unless-stopped`, so they come
back after a daemon restart or a crash but stay down after a deliberate
`docker compose stop`. The monitor baselines state on its first poll after any
restart, so a restart does not emit a burst of false alerts. The digest task
schedules on a fixed time of day with no catch-up, so a restart that spans
`REPORT_HOUR_UTC` skips that day's digest.

**Shutdown.** `_Bot.close()` closes the SQLite checkpointer before discord.py's
own shutdown. That matters because the checkpointer holds an aiosqlite worker
thread that would otherwise outlive the event loop and hold the process open
until `docker stop` gives up and sends SIGKILL.

**Where to look when something is wrong.**

- `DISCORD_LOG_CHANNEL_ID` mirrors the bot's own log records at INFO and above
  into a channel, which is the fastest read on a running bot. Records from
  discord.py's own loggers are excluded, and `httpx`/`httpx2` are pinned to
  WARNING, so the channel shows the agent's activity rather than one line per
  HTTP call.
- `docker compose logs -f bot` for everything, including the discord.py records
  that do not reach the log channel and anything that fails before `on_ready`
  attaches the handler (a bad token, a missing intent, a failed sync).
- `docker compose logs prometheus loki promtail` when queries come back empty:
  an empty Loki result is usually Promtail not shipping, and an empty Prometheus
  result is usually the missing exporter targets above.
- The bot answering "Investigation failed: ..." points at the LLM endpoint;
  check `LLM_BASE_URL` is reachable from the bot's network namespace.
