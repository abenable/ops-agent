"""Docker container tools via the Docker Engine API."""

import os
from urllib.parse import urlparse

import httpx2 as httpx


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
        # ponytail: daemon unreachable or erroring — treat as no containers, like a missing socket
        return []


def container_name(container: dict) -> str:
    """Human name for a Docker API container object."""
    names = container.get("Names") or []
    return names[0].lstrip("/") if names else container.get("Id", "")[:12]


async def find_container(service: str) -> dict | None:
    """Match a container by name substring (case-insensitive). None if not found."""
    needle = service.lower()
    for c in await list_containers(all_containers=True):
        if needle in container_name(c).lower():
            return c
    return None


async def container_logs(container_id: str, tail: int = 20) -> str:
    """Fetch the last `tail` lines of a container's combined stdout/stderr."""
    async with _docker_client() as client:
        response = await client.get(
            f"/v1.40/containers/{container_id}/logs",
            params={
                "stdout": "true",
                "stderr": "true",
                "tail": tail,
            },
        )
        response.raise_for_status()
        return response.text


async def restart_container(container_id: str, timeout: int = 10) -> dict:
    """Restart a Docker container."""
    async with _docker_client() as client:
        response = await client.post(
            f"/v1.40/containers/{container_id}/restart",
            params={"t": timeout},
        )
        response.raise_for_status()
        return {"container_id": container_id, "restarted": True}
