# Tool catalog

The tool surface is what the LLM can reach. It lives in `src/agent/tools/` and is
exported as `ALL_TOOLS` from `src/agent/tools/__init__.py`: ten LangChain tools
grouped by backend (Docker, Prometheus, Loki). `src/agent/workflows/investigate.py`
binds all ten; the engine in `src/agent/engine.py` knows nothing about any of them.

## Shape

Each of `docker.py`, `prometheus.py` and `loki.py` is split into two halves by a
comment banner.

The upper half is a thin async client over `httpx2`. Plain `async def` functions,
no classes, no connection pooling held between calls: each one opens an
`httpx.AsyncClient` in a `with` block, issues one GET with a 10 second timeout,
calls `raise_for_status()` and returns parsed JSON (or, for Docker logs, bytes).
These are importable and testable without any LangChain machinery, and the
monitor and digest layers call them directly rather than going through the tools.

The lower half is the LangChain `@tool` half. Every tool is `async def`, takes
plain scalars, and returns a `str`, because the model consumes the return value
as message text. That is also where clamping happens: `tail`, `limit` and
`minutes` are clamped in the tool, not in the client, so a direct caller can ask
for whatever it wants and only the model-facing path is fenced.

Return values are bounded. The query tools stringify their result and slice it to
4000 characters. The discovery tools (`list_metric_names`, `get_label_values`,
`get_loki_label_values`) instead cap at 250 entries, joined by newlines.
`docker_status` returns a single short line and needs no cap. The point is the
same in every case: a tool result becomes part of the next prompt, so an
unbounded result would eat the context window.

Failure is returned, not raised, wherever the failure is expected: a name that
matches nothing, an ambiguous name, or an unreachable Docker socket all come back
as a parenthesised string the model can read. Transport failures against
Prometheus and Loki do propagate, and the engine catches them and feeds
`(tool 'x' failed: ...)` back to the model.

## Reference

| Tool | Arguments | Returns | Limit |
| --- | --- | --- | --- |
| `list_services` | none | `Containers: a, b, c` and `Monitored endpoints: name=url, ...`, two lines | 4000 chars |
| `docker_status` | `container: str` | `<name>: state=..., status=..., image=...` | none needed (one line) |
| `docker_logs` | `container: str`, `tail: int = 50` | combined stdout/stderr, demultiplexed and stripped of non-printable bytes | `tail` clamped to 1..200, output 4000 chars |
| `query_prometheus` | `promql: str` | `str()` of the Prometheus instant-query JSON | 4000 chars |
| `query_prometheus_range` | `promql: str`, `minutes: int` | `str()` of the range-query JSON | `minutes` clamped to 1..`RANGE_MAX_HOURS * 60` (default 360), output 4000 chars |
| `list_metric_names` | `match: str = ""` | one metric name per line, substring filtered when `match` is set | client returns at most 500, tool prints at most 250 |
| `get_label_values` | `label: str` | one Prometheus label value per line | at most 250 lines; invalid label name yields no values |
| `get_loki_label_values` | `label: str` | one Loki stream-label value per line | at most 250 lines; invalid label name yields no values |
| `query_loki` | `logql: str`, `limit: int = 100` | `str()` of the Loki JSON for the last 15 minutes | `limit` clamped to 1..`LOKI_MAX_LIMIT` (default 500), output 4000 chars |
| `query_loki_range` | `logql: str`, `minutes: int`, `limit: int = 100` | `str()` of the Loki range JSON | `limit` as above, `minutes` clamped to 1..`RANGE_MAX_HOURS * 60`, output 4000 chars |

Empty results are explicit rather than blank: `(no metrics found)`,
`(no values for label X)`, `(no logs)`, `(no container matching 'X')`. A model
handles a stated negative far better than an empty string.

## Docker

`src/agent/tools/docker.py` talks the Engine API directly over `httpx2`. There is
no `docker` SDK dependency and no shelling out to the CLI. Every path is pinned
to API version v1.40 (`/v1.40/containers/json`, `/v1.40/containers/{id}/logs`).

### Transport

`_docker_client()` branches on the host string:

```python
if docker_host.startswith("unix://"):
    transport = httpx.AsyncHTTPTransport(uds=docker_host[7:])
    return httpx.AsyncClient(base_url="http://localhost", transport=transport, timeout=10)
parsed = urlparse(docker_host)
base_url = f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 2375}"
```

A Unix socket goes through httpx's `uds` transport with a `http://localhost` base
URL, because the Engine API still wants a valid `Host` header even when there is
no TCP connection. A `tcp://` host is used as-is, defaulting to port 2375.

### The DOCKER_HOST empty-string fallback

```python
def _docker_host() -> str:
    return os.environ.get("DOCKER_HOST") or "unix:///var/run/docker.sock"
```

The `or` is load-bearing and cannot be replaced with
`os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock")`. Compose files and
`.env` files routinely contain a bare `DOCKER_HOST=`, which sets the variable to
the empty string rather than leaving it unset. With the two-argument `get`, that
empty string wins over the default, reaches the transport layer, and breaks every
Docker call. With `or`, an empty value falls through to the socket path.

### Graceful degradation

`_docker_available()` returns `True` for any `tcp://` host and, for a `unix://`
host, checks that the socket path exists on disk. `list_containers()` consults it
first, and wraps the request in `except httpx.HTTPError: return []`. So a missing
socket mount or a stopped daemon produces an empty container list, not an
exception. That empty list surfaces as
`Containers: (none / docker unreachable)` from `list_services`, and as
`- none in scope (is the Docker socket mounted?)` in a digest snapshot. The
monitor, which calls the client directly, keeps polling instead of dying.

### Log stream framing

Every container in this stack runs without a TTY, and the Engine API frames
non-TTY log output: an 8 byte header per chunk (1 byte stream type, 3 reserved
bytes, then a 4 byte big-endian payload length), followed by the payload.
Concatenating the raw response gives binary noise interleaved with the text.
`_demux_docker_stream()` walks the buffer, reads the length from bytes 4..8 of
each header, copies the payload, and jumps to the next header:

```python
while i + 8 <= n:
    length = int.from_bytes(data[i + 4 : i + 8], "big")
    start = i + 8
    end = min(start + length, n)
    out += data[start:end]
    i = start + length
```

The `min(start + length, n)` guards a truncated final frame. Decoding uses
`errors="replace"`, so a partial multi-byte character cannot raise. On top of
that, `docker_logs` drops anything that is not printable except `\n` and `\t`,
which removes ANSI colour escapes and control bytes that would otherwise waste
context and confuse the model.

`tail` defaults to 50 and is clamped to a maximum of 200 lines
(`tail = max(1, min(tail, 200))`). A container that logs long JSON lines can
still blow past 4000 characters at 200 lines, and the final slice takes the
first 4000 characters of what came back.

## Prometheus

`src/agent/tools/prometheus.py` uses the standard HTTP API under
`settings.prometheus_url` (default `http://localhost:9090`).

### Instant versus range

`query()` hits `/api/v1/query` with just `query=<promql>`: one evaluation, at
Prometheus's notion of now. Use it for current values (`up == 0`).

`query_range()` hits `/api/v1/query_range` and computes the window itself from a
`minutes` argument: `end = now(UTC)`, `start = end - minutes`. The step is
derived rather than passed in:

```python
step_seconds = max(15, minutes * 60 // 100)
```

That targets roughly 100 data points across whatever window was asked for, with a
15 second floor. A 30 minute window gets an 18 second step; a 6 hour window gets
216 seconds. Fixing the point count rather than the resolution is what keeps the
serialized JSON inside the 4000 character budget regardless of window size.
`minutes` is clamped in the tool to `RANGE_MAX_HOURS * 60`.

### Discovery

`metric_names(match="")` reads `/api/v1/label/__name__/values`, the metric name
list, filters case-insensitively by substring when `match` is given, and returns
at most 500. `label_values(label)` reads `/api/v1/label/{label}/values`. Both
exist so the model can find out what actually exists before writing a query
instead of inventing a metric name that was never scraped.

### The label-name guard

```python
_LABEL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
```

`label_values()` returns `[]` immediately if the label does not match. This is
not cosmetic validation of a Prometheus naming rule: the label goes into a URL
*path* segment, `f"{settings.prometheus_url}/api/v1/label/{label}/values"`, where
httpx will not escape it for us. An unvalidated label containing `/` or `..`
walks to a different API path, a `?` starts a query string, and a `#` truncates
the rest of the URL. Whitespace and everything else outside the character class
is rejected for the same reason. The model is the one supplying this string, so
it is a trust boundary.

### Authentication

`_headers()` returns `{"Authorization": f"Bearer {settings.prometheus_token}"}`
only when `PROMETHEUS_TOKEN` is non-empty, otherwise an empty dict. An
unauthenticated local Prometheus needs no configuration, and a proxied one in
front of an auth layer works by setting one variable.

## Loki

`src/agent/tools/loki.py` mirrors the Prometheus module: same two halves, same
`_LABEL_RE` guard on `label_values()` for the same URL path reason, same
`_headers()` bearer pattern keyed on `LOKI_TOKEN`.

### Why `query()` is a range query

Loki has an instant endpoint at `/loki/api/v1/query`, and this module does not
use it. Loki rejects a plain log-stream selector there with "log queries are not
supported as an instant query type": that endpoint only accepts metric queries
(`rate(...)`, `count_over_time(...)`), not `{job="x"}`. Since the model's natural
move is a bare selector, an instant endpoint would fail on the most common query
it writes. `query()` therefore delegates:

```python
async def query(logql: str, limit: int = 100) -> dict:
    return await query_range(logql, minutes=15, limit=limit)
```

The `query_loki` tool is described to the model as an instant query, and behaves
like one from its point of view: recent logs, no window argument. The 15 minute
window is the implementation detail that makes that true. `query_loki_range`
exists for anything wider and takes an explicit `minutes`.

### Loki labels are not Prometheus labels

This is the operational point that matters most when extending the agent. Loki's
stream labels come from Promtail's scrape config, not from Docker and not from
Prometheus. In this stack, the `promtail-config` block in `docker-compose.yml`
sets exactly three: `service` (from the compose service label, so a container
started outside compose has no value for it), `container` (the Docker name with
its leading slash stripped) and `job` (constant `docker-logs`). Edit that
config, or point the agent at a Loki fed by a different shipper or by a
non-Docker source, and the label set changes with it. Nothing keeps it aligned
with Prometheus's labels, and a deployment with no `container` label at all is
normal.

So a model that reasons "the container is called `marconi-agent-api`, therefore
`{container="marconi-agent-api"}`" is guessing at a schema it has not read. When
the guess is wrong the result is empty with no error, which is the worst failure
mode available: it looks like "no logs" rather than "wrong query". The tool
descriptions push back on this directly. The docstring of
`get_loki_label_values`, which is what the model sees as the tool description,
reads:

```text
List values for a Loki stream label such as 'service' or 'job'. Loki's
label schema is set by Promtail and is NOT the same as Prometheus's or a
Docker container name - do not guess a label like 'container'; call this
first to learn the real label values before writing a LogQL selector.
```

Discovery first, then a selector built from real values. The same warning is
repeated on the client function `label_values()` so a human reading the code
sees it too.

## Name resolution

Every container and watch-list lookup goes through one function,
`resolve_one()` in `src/agent/normalize.py`. Nothing does its own matching.

`normalize()` strips `[-_\s.]+` and lowercases, so separator style stops
mattering:

```python
normalize("agent_api") == normalize("agent-api") == normalize("agentapi") == "agentapi"
```

`resolve_one()` collects every candidate whose normalized name *contains* the
normalized needle, then applies two rules:

1. An exact normalized match wins. Given containers `agent_api` and
   `marconi-agent-api-worker`, the query `agent-api` returns `agent_api` even
   though both are substring matches.
2. More than one substring match and no exact match raises `AmbiguousName`, a
   `LookupError` carrying the sorted candidate list. Given `marconi-agent-api`
   and `marconi-agent-worker`, the query `agent` raises
   `'agent' matches 2 containers: marconi-agent-api, marconi-agent-worker - use one of these exact names`.

Zero matches return `None`.

Ambiguity raises rather than returning the first hit on purpose. Silently picking
one reports the state of a container the caller did not ask about, under the name
they did ask about, which is a wrong answer that reads as a right one. The tools
turn both outcomes into text the model can act on: `docker_status` and
`docker_logs` catch `AmbiguousName` and return `(exc)`, whose message already
lists the exact names to retry with, and return
`(no container matching 'X')` for `None`.

## Read-only by construction

Nothing in `src/agent/tools/` issues anything but a GET. There is no
`/containers/{id}/restart`, no `/kill`, no `/exec`, no Prometheus admin API call,
no Loki delete. The mutating half of each backend's API is simply not written.

That matters because the agent's other defences are softer. The system prompt
tells the model it is read-only, but a prompt is an instruction to a model, not a
constraint on one. The compose file mounts the Docker socket, and its own comment
records that a `:ro` mount only makes the socket *file* read-only: the Engine API
behind it stays fully writable, and socket access is root-equivalent on the host.

The guarantee comes from the tool list. A model can only call what it was bound
to, and it was bound to ten read-only functions, so the worst outcome of a
confused model, a prompt injection carried in a log line, or a mis-parsed tool
call is a wasted query. Anything added to `ALL_TOOLS` inherits that
responsibility: adding one mutating tool removes the property for the whole
agent, prompt text notwithstanding.
