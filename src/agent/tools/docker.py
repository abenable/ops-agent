"""Read-only Docker client (Engine API over httpx2) + LangChain tools.

With ``NODES`` set, every node has its own Docker endpoint, containers carry a
``Node`` key, and their names are qualified as ``node/container``.
"""

import asyncio
import os
import re
from urllib.parse import urlparse

import httpcore2
import httpx2 as httpx
from langchain_core.tools import tool

from agent.config.settings import settings
from agent.normalize import AmbiguousName, resolve_one


def _docker_host() -> str:
    """DOCKER_HOST from the env, falling back to the local socket."""
    return os.environ.get("DOCKER_HOST") or "unix:///var/run/docker.sock"


def docker_nodes() -> dict[str, str]:
    """``NODES`` as ``name -> Docker URL``, in the order given. Empty when unset."""
    out: dict[str, str] = {}
    for pair in re.split(r"[\s,]+", settings.nodes.strip()):
        name, _, target = pair.partition("=")
        name, target = name.strip(), target.strip()
        if not (name and target):
            continue
        if "://" not in target:
            user = settings.node_ssh_user
            target = f"ssh://{user}@{target}" if user and "@" not in target else f"ssh://{target}"
        out[name] = target
    return out


def ssh_command(target: str) -> list[str]:
    """The ssh argv that bridges stdin/stdout to the Docker daemon on ``target`` (ssh://[user@]host[:port])."""
    parsed = urlparse(target)
    host = f"{parsed.username}@{parsed.hostname}" if parsed.username else parsed.hostname
    argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=accept-new"]
    if parsed.port:
        argv += ["-p", str(parsed.port)]
    if key := settings.node_ssh_key:
        # Keep known_hosts beside the key, so a container's mounted key dir persists it.
        known = os.path.join(os.path.dirname(key), "known_hosts")
        argv += ["-i", key, "-o", "IdentitiesOnly=yes", "-o", f"UserKnownHostsFile={known}"]
    # `docker system dial-stdio` is how the Docker CLI itself talks to ssh:// hosts.
    return [*argv, host, "docker", "system", "dial-stdio"]


class _PipeStream(httpcore2.AsyncNetworkStream):
    """An HTTP connection over a subprocess's stdin/stdout."""

    def __init__(self, proc: asyncio.subprocess.Process):
        self._proc = proc

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        data = await asyncio.wait_for(self._proc.stdout.read(max_bytes), timeout)
        if not data:
            # EOF can arrive before the exit is reaped; wait for it so ssh's error isn't lost.
            try:
                await asyncio.wait_for(self._proc.wait(), 2)
            except TimeoutError:
                pass
        if not data and self._proc.returncode not in (None, 0):
            err = (await self._proc.stderr.read()).decode(errors="replace").strip()
            raise httpcore2.ConnectError(err or f"exited with {self._proc.returncode}")
        return data

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self._proc.stdin.write(buffer)
        await asyncio.wait_for(self._proc.stdin.drain(), timeout)

    async def aclose(self) -> None:
        if self._proc.returncode is None:
            self._proc.kill()
        await self._proc.wait()


class _CommandBackend(httpcore2.AsyncNetworkBackend):
    """Opens every connection by running ``argv``, whatever host the URL names."""

    def __init__(self, argv: list[str]):
        self._argv = argv

    async def _open(self) -> _PipeStream:
        proc = await asyncio.create_subprocess_exec(
            *self._argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        return _PipeStream(proc)

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        return await self._open()

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        return await self._open()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


def command_transport(argv: list[str]) -> httpx.AsyncHTTPTransport:
    transport = httpx.AsyncHTTPTransport()
    # ponytail: httpx exposes no network_backend option, so the pool is swapped; one ssh
    # handshake per client (~0.5 s on a Pi). Add ssh ControlMaster if that gets slow.
    transport._pool = httpcore2.AsyncConnectionPool(network_backend=_CommandBackend(argv))
    return transport


def _docker_client(target: str | None = None) -> httpx.AsyncClient:
    """An httpx client for a Docker URL (unix://, tcp://, ssh://); DOCKER_HOST by default."""
    docker_host = target or _docker_host()
    if docker_host.startswith("unix://"):
        transport = httpx.AsyncHTTPTransport(uds=docker_host[7:])
        return httpx.AsyncClient(base_url="http://localhost", transport=transport, timeout=10)
    if docker_host.startswith("ssh://"):
        transport = command_transport(ssh_command(docker_host))
        return httpx.AsyncClient(base_url="http://docker", transport=transport, timeout=15)
    parsed = urlparse(docker_host)
    base_url = f"http://{parsed.hostname}:{parsed.port or 2375}"
    return httpx.AsyncClient(base_url=base_url, timeout=10)


def _docker_available(target: str | None = None) -> bool:
    """Best-effort check for a usable Docker endpoint."""
    docker_host = target or _docker_host()
    if docker_host.startswith(("tcp://", "ssh://")):
        return True
    if docker_host.startswith("unix://"):
        return os.path.exists(docker_host[7:])
    return False


async def _list(target: str | None, all_containers: bool) -> list[dict] | None:
    """Containers at one Docker endpoint; None when it can't be reached."""
    if not _docker_available(target):
        return None
    try:
        async with _docker_client(target) as client:
            response = await client.get(
                "/v1.40/containers/json",
                params={"all": str(all_containers).lower()},
            )
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, OSError, TimeoutError):
        return None


async def containers_by_node(all_containers: bool = True) -> dict[str, list[dict] | None]:
    """Each node's containers (tagged with ``Node``), None for a node that can't be reached."""
    nodes = docker_nodes()
    found = await asyncio.gather(*(_list(t, all_containers) for t in nodes.values()))
    out: dict[str, list[dict] | None] = {}
    for name, containers in zip(nodes, found, strict=True):
        out[name] = None if containers is None else [{**c, "Node": name} for c in containers]
    return out


async def list_containers(all_containers: bool = True) -> list[dict]:
    """List running (or all) Docker containers on every node. Unreachable nodes are skipped."""
    if not settings.nodes:
        return await _list(None, all_containers) or []
    return [c for cs in (await containers_by_node(all_containers)).values() for c in cs or []]


def container_name(container: dict) -> str:
    """Human name for a Docker API container object: ``node/name`` on a multi-node cluster."""
    names = container.get("Names") or []
    name = names[0].lstrip("/") if names else container.get("Id", "")[:12]
    return f"{container['Node']}/{name}" if container.get("Node") else name


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


async def container_logs(container_id: str, tail: int = 50, node: str | None = None) -> str:
    """Fetch a container's last `tail` lines of combined stdout/stderr."""
    async with _docker_client(docker_nodes().get(node) if node else None) as client:
        response = await client.get(
            f"/v1.40/containers/{container_id}/logs",
            params={"stdout": "true", "stderr": "true", "tail": tail},
        )
        response.raise_for_status()
        return _demux_docker_stream(response.content)


@tool
async def list_services() -> str:
    """List known infrastructure targets by their real names: Docker container names and configured monitored endpoints. Call this FIRST when you are unsure of the exact service name."""
    unreachable: list[str] = []
    if settings.nodes:
        by_node = await containers_by_node()
        unreachable = [n for n, cs in by_node.items() if cs is None]
        names = [container_name(c) for cs in by_node.values() for c in cs or []]
    else:
        names = [container_name(c) for c in await list_containers(all_containers=True)]
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
    if unreachable:
        lines.append("Nodes whose Docker could not be reached: " + ", ".join(unreachable))
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
    raw = await container_logs(target.get("Id") or container_name(target), tail=tail, node=target.get("Node"))
    cleaned = "".join(c for c in raw if c.isprintable() or c in "\n\t")
    return cleaned[:4000] or "(no logs)"
