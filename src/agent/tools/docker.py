"""Read-only Docker client (Engine API over httpx2) + LangChain tools."""

import os
from urllib.parse import urlparse

import httpx2 as httpx
from langchain_core.tools import tool

from agent.config.settings import settings
from agent.normalize import AmbiguousName, resolve_one


def _docker_host() -> str:
    """DOCKER_HOST from the env, falling back to the local socket."""
    return os.environ.get("DOCKER_HOST") or "unix:///var/run/docker.sock"


def _docker_client() -> httpx.AsyncClient:
    """Build an httpx client for the local Docker socket or TCP host."""
    docker_host = _docker_host()
    if docker_host.startswith("unix://"):
        transport = httpx.AsyncHTTPTransport(uds=docker_host[7:])
        return httpx.AsyncClient(
            base_url="http://localhost", transport=transport, timeout=10
        )
    parsed = urlparse(docker_host)
    base_url = f"http://{parsed.hostname}:{parsed.port or 2375}"
    return httpx.AsyncClient(base_url=base_url, timeout=10)


def _docker_available() -> bool:
    """Best-effort check for a usable Docker socket."""
    docker_host = _docker_host()
    if docker_host.startswith("tcp://"):
        return True
    if docker_host.startswith("unix://"):
        return os.path.exists(docker_host[7:])
    return False


async def list_containers(all_containers: bool = True) -> list[dict]:
    """List running (or all) Docker containers. [] when Docker is unreachable."""
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
    containers = await list_containers(all_containers=True)
    return resolve_one(service, containers, container_name, kind="containers")


async def resolve_container_name(service: str) -> str | None:
    """Resolve a partial/separator-variant name to the exact container name."""
    container = await find_container(service)
    return container_name(container) if container else None


def _demux_docker_stream(data: bytes) -> str:
    """Strip Docker's 8-byte stream-framing headers from a log response."""
    out = bytearray()
    i, n = 0, len(data)
    while i + 8 <= n:
        length = int.from_bytes(data[i + 4 : i + 8], "big")
        start = i + 8
        end = min(start + length, n)
        out += data[start:end]
        i = start + length
    return out.decode("utf-8", errors="replace")


async def container_logs(container_id: str, tail: int = 50) -> str:
    """Fetch a container's last `tail` lines of combined stdout/stderr."""
    async with _docker_client() as client:
        response = await client.get(
            f"/v1.40/containers/{container_id}/logs",
            params={"stdout": "true", "stderr": "true", "tail": tail},
        )
        response.raise_for_status()
        return _demux_docker_stream(response.content)


@tool
async def list_services() -> str:
    """List known infrastructure targets by their real names: Docker container names and configured monitored endpoints. Call this FIRST when you are unsure of the exact service name."""
    containers = await list_containers(all_containers=True)
    names = [container_name(c) for c in containers]
    endpoints: list[str] = []
    for pair in settings.monitored_endpoints.split(","):
        if "=" in pair:
            n, u = pair.split("=", 1)
            n, u = n.strip(), u.strip()
            if n and u:
                endpoints.append(f"{n}={u}")
    lines = [
        "Containers: " + (", ".join(names) if names else "(none / docker unreachable)"),
        "Monitored endpoints: "
        + (", ".join(endpoints) if endpoints else "(none configured)"),
    ]
    return "\n".join(lines)[:4000]


@tool
async def docker_status(container: str) -> str:
    """Return the state of a Docker container (read-only): state, status, image. Use a container name returned by list_services. Matching is separator-agnostic so 'agent_api' matches 'marconi-agent-api'."""
    try:
        target = await find_container(container)
    except AmbiguousName as exc:
        return f"({exc})"
    if target is None:
        return f"(no container matching '{container}')"
    name = container_name(target)
    return (
        f"{name}: state={target.get('State')}, "
        f"status={target.get('Status')}, image={target.get('Image')}"
    )


@tool
async def docker_logs(container: str, tail: int = 50) -> str:
    """Fetch the last `tail` lines of a Docker container's stdout/stderr logs (read-only). Use this when Loki has no logs for a container, or to read a container's own output directly. Use a container name from list_services; `tail` is capped at 200."""
    tail = max(1, min(tail, 200))
    try:
        target = await find_container(container)
    except AmbiguousName as exc:
        return f"({exc})"
    if target is None:
        return f"(no container matching '{container}')"
    raw = await container_logs(target.get("Id") or container_name(target), tail=tail)
    cleaned = "".join(c for c in raw if c.isprintable() or c in "\n\t")
    return cleaned[:4000] or "(no logs)"
