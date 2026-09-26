# The HTTP API

`agent api` starts a FastAPI service over the same workflows the Discord bot
runs. It exists so the agent is reachable from something that is not Discord —
a script, a dashboard, a CI job — without a second implementation of anything.

```bash
agent api                      # binds API_HOST:API_PORT
agent api --host 127.0.0.1 --port 8080
```

Interactive docs are at `/docs`, the schema at `/openapi.json`.

## Routes

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness. The only route that never needs a key. |
| `GET` | `/services` | Container names and monitored endpoints — the names the agent resolves against. |
| `GET` | `/containers` | Every in-scope container with state, status text, and image. |
| `GET` | `/status` | Current health of containers and endpoints, with `containers_down` / `endpoints_down` called out. |
| `GET` | `/events?hours=24` | Recorded up/down transitions. `hours` is 1–2160 (the event log keeps 90 days). |
| `POST` | `/investigate` | `{"question": "...", "thread_id": "..."}` → the agent's answer. |
| `POST` | `/report` | `{"service": "..."}` → a structured incident report. |
| `GET` | `/digest/{daily\|weekly}` | Render a digest without waiting for its scheduled hour. |
| `GET` | `/watchlist` | Containers pinned into monitoring scope. |
| `POST` | `/watchlist` | `{"container": "..."}` pins one. |
| `DELETE` | `/watchlist/{name}` | Unpins one. Matching is separator-agnostic. |

```bash
curl -s localhost:8000/status | jq '.containers_down'
curl -s -X POST localhost:8000/investigate \
  -H 'content-type: application/json' \
  -d '{"question": "is loki healthy?"}' | jq -r .answer
```

## Authentication

Set `API_KEY` and every route except `/health` requires a matching `X-API-Key`
header; leave it unset and the API is open.

```bash
curl -s localhost:8000/status -H "X-API-Key: $API_KEY"
```

Unset is the default because Compose binds the API to loopback, and the host is
only reachable over the lab's mesh network. That assumption is the whole
security model, so it stops holding the moment the port is exposed more widely —
set a key before that happens, not after.

## What it cannot do

The API is read-only in the same sense the agent is: it calls the same tool
layer, and no tool in that layer mutates anything. The one exception is the
watch list, which is the agent's own configuration rather than infrastructure —
pinning a container changes what gets monitored, never the container.

## Status codes

| Code | When |
|---|---|
| `401` | `API_KEY` is set and the header is missing or wrong. |
| `404` | Unpinning a container that is not on the watch list. |
| `422` | A malformed body, an unknown digest kind, or `hours` out of range. |
| `503` | Docker is unreachable. A dependency being down is not a bug in the API, so it is not a `500`. |

## Running it alongside the bot

Both processes open `memory.db`. SQLite is in WAL mode, so concurrent access
works, but two writers is a different shape from the single-writer design
[architecture.md](architecture.md) describes. Conversations are keyed by
`thread_id`, and the bot uses Discord channel ids — pass API thread ids that
cannot collide with those if you do not want the two surfaces sharing history.

Compose runs both by default. Nothing requires the API: `docker compose up -d
bot` starts the bot alone.
