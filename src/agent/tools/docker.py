"""Docker container tools via the Docker Engine API."""

import os
from urllib.parse import urlparse

import httpx2 as httpx

from agent.tools.normalize import normalize


def _docker_client():
    """Build an httpx client for the local Docker socket or TCP host."""
    docker_host = os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock")

    if docker_host.startswith("unix://"):
        socket_path = docker_host[7:]
        transport = httpx.AsyncHTTPTransport(uds=socket_path)
        # Docker API over a Unix socket expects a localhost Host header.
        base_url = "http://localhost"
    else:
        parsed = urlparse(docker_host)
        base_url = f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 2375}"
        transport = None

    return httpx.AsyncClient(base_url=base_url, transport=transport, timeout=10)


def _docker_available() -> bool:
    """Best-effort check for a usable Docker socket."""
    docker_host = os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock")
    if docker_host.startswith("tcp://"):
        return True
    if docker_host.startswith("unix://"):
        return os.path.exists(docker_host[7:])
    return False


async def list_containers(all_containers: bool = True) -> list[dict]:
    """List running (or all) Docker containers."""
    if not _docker_available():
        return []

    try:
        async with _docker_client() as client:
            response = await client.get(
                "/v1.40/containers/json",
                params={"all": str(all_containers).lower()},
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError:
        return []


def container_name(container: dict) -> str:
    """Human name for a Docker API container object."""
    names = container.get("Names") or []
    return names[0].lstrip("/") if names else container.get("Id", "")[:12]


async def find_container(service: str) -> dict | None:
    """Match a container by name, separator-agnostic. None if not found."""
    needle = normalize(service)
    for c in await list_containers(all_containers=True):
        if needle in normalize(container_name(c)):
            return c
    return None


async def resolve_container_name(service: str) -> str | None:
    """Resolve a partial/separator-variant name to the exact Docker container name."""
    container = await find_container(service)
    return container_name(container) if container else None


def compose_service_name(container: dict) -> str | None:
    """The docker-compose service key for this container (e.g. 'n8n'), read
    from the 'com.docker.compose.service' label Compose sets automatically.

    This is the identifier Prometheus scrape jobs and Promtail stream labels
    are keyed on in this stack — NOT the container name, which Compose
    prefixes with the project name (e.g. 'marconi-agent-n8n'). None for
    containers Compose didn't create.
    """
    return (container.get("Labels") or {}).get("com.docker.compose.service")


async def resolve_label_name(service: str) -> str:
    """Resolve a service/container name (any spelling: short, full, typo'd
    separators) to the identifier Loki/Prometheus labels actually use in this
    stack — the docker-compose service key, not the Docker container name.

    Observability backends here are labeled with the short compose key
    ('n8n'), while callers (the web dashboard, Discord button targets) often
    pass the full container name ('marconi-agent-n8n'). Matching the full name
    against a Loki/Prometheus selector built for the short key silently
    matches nothing. Falls back to the input unchanged if no container is
    found or it carries no compose label, so callers degrade gracefully
    instead of raising.
    """
    container = await find_container(service)
    if container is None:
        return service
    return compose_service_name(container) or container_name(container)


def _demux_docker_stream(data: bytes) -> str:
    """Strip Docker's stdout/stderr stream-multiplexing framing.

    The Engine API returns non-tty container logs (the default for
    compose-managed services — none in this stack set ``tty: true``) as
    repeated frames: 1 byte stream type + 3 reserved bytes + 4-byte
    big-endian payload length, then that many payload bytes. A naive
    printable-char filter mostly removes the header (3 of its first 4 bytes
    are always 0x00) but leaves the length field's low byte whenever it
    lands in printable ASCII range — a stray character glued onto the front
    of a line, which broke the collector's ``<ts> <message>`` line parsing.
    # ponytail: assumes non-tty logs (true for every service here); a tty
    # container's unframed stream would be misparsed by this.
    """
    out = bytearray()
    i, n = 0, len(data)
    while i + 8 <= n:
        length = int.from_bytes(data[i + 4 : i + 8], "big")
        start = i + 8
        end = min(start + length, n)
        out += data[start:end]
        i = start + length
    return out.decode("utf-8", errors="replace")


async def container_logs(
    container_id: str,
    tail: int = 20,
    since: str | None = None,
    timestamps: bool = False,
) -> str:
    """Fetch a container's combined stdout/stderr.

    With ``since`` (RFC3339 timestamp or unix seconds) returns only lines after
    that instant; ``tail`` is forced to ``"all"`` in that case so ``since``
    actually bounds the window rather than being applied to the last N. With
    ``timestamps=True`` the Engine API prefixes each line with its RFC3339 ts.
    """
    params = {"stdout": "true", "stderr": "true"}
    if since is not None:
        params["since"] = since
        params["tail"] = "all"
    else:
        params["tail"] = tail
    if timestamps:
        params["timestamps"] = "true"
    async with _docker_client() as client:
        response = await client.get(
            f"/v1.40/containers/{container_id}/logs",
            params=params,
        )
        response.raise_for_status()
        return _demux_docker_stream(response.content)


async def restart_container(container_id: str, timeout: int = 10) -> dict:
    """Restart a Docker container."""
    async with _docker_client() as client:
        response = await client.post(
            f"/v1.40/containers/{container_id}/restart",
            params={"t": timeout},
        )
        response.raise_for_status()
        return {"container_id": container_id, "restarted": True}
