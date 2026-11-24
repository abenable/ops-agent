"""Tests for multi-node Docker access and the node tools."""

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock

import httpx2 as httpx
import pytest

from agent.bot import monitor
from agent.config.settings import Settings, settings
from agent.tools import configured_tools, docker, nodes

# A one-shot HTTP server on stdin/stdout, standing in for `docker system dial-stdio`.
FAKE_DAEMON = (
    "import sys\n"
    "while sys.stdin.buffer.readline() not in (b'\\r\\n', b''): pass\n"
    "body = b'[{\"Names\": [\"/web\"], \"State\": \"running\"}]'\n"
    "sys.stdout.buffer.write(b'HTTP/1.1 200 OK\\r\\nContent-Type: application/json\\r\\n'\n"
    "    + b'Content-Length: %d\\r\\n\\r\\n' % len(body) + body)\n"
    "sys.stdout.flush()\n"
)


@pytest.fixture
def cluster(monkeypatch):
    monkeypatch.setattr(settings, "nodes", "ctl=unix:///var/run/docker.sock pi1=192.168.88.11")
    monkeypatch.setattr(settings, "node_ssh_user", "admin")
    monkeypatch.setattr(settings, "node_ssh_key", "")


def test_nodes_parse_like_hosts_env(cluster, monkeypatch):
    assert docker.docker_nodes() == {"ctl": "unix:///var/run/docker.sock", "pi1": "ssh://admin@192.168.88.11"}
    monkeypatch.setattr(settings, "nodes", "a=root@h1, b=ssh://u@h2:2222,,=x")
    assert docker.docker_nodes() == {"a": "ssh://root@h1", "b": "ssh://u@h2:2222"}
    monkeypatch.setattr(settings, "nodes", "")
    assert docker.docker_nodes() == {}


def test_ssh_command_reaches_docker_through_dial_stdio(monkeypatch):
    monkeypatch.setattr(settings, "node_ssh_key", "/app/data/ssh/id_ed25519")
    argv = docker.ssh_command("ssh://admin@pi1:2222")
    assert argv[0] == "ssh" and "BatchMode=yes" in argv
    assert argv[argv.index("-p") + 1] == "2222"
    assert "UserKnownHostsFile=/app/data/ssh/known_hosts" in argv
    assert argv[-4:] == ["admin@pi1", "docker", "system", "dial-stdio"]


def test_command_transport_speaks_http_over_a_pipe():
    async def run(argv):
        async with httpx.AsyncClient(base_url="http://docker", transport=docker.command_transport(argv)) as client:
            return (await client.get("/v1.40/containers/json")).json()

    assert asyncio.run(run([sys.executable, "-c", FAKE_DAEMON])) == [{"Names": ["/web"], "State": "running"}]
    # A command that fails (ssh refused, docker missing) is a connection error carrying its stderr.
    fail = [sys.executable, "-c", "import sys; sys.stderr.write('no route to host'); sys.exit(255)"]
    with pytest.raises(httpx.ConnectError, match="no route to host"):
        asyncio.run(run(fail))


def test_containers_are_named_by_node_and_unreachable_nodes_skipped(cluster, monkeypatch):
    async def fake_list(target, all_containers):
        return None if target.startswith("ssh://") else [{"Names": ["/loki"], "State": "running"}]

    monkeypatch.setattr(docker, "_list", fake_list)
    by_node = asyncio.run(docker.containers_by_node())
    assert by_node["pi1"] is None
    found = asyncio.run(docker.list_containers())
    assert [docker.container_name(c) for c in found] == ["ctl/loki"]
    out = asyncio.run(docker.list_services.ainvoke({}))
    assert "ctl/loki" in out and "could not be reached: pi1" in out


def test_watching_a_bare_name_covers_it_on_every_node(monkeypatch):
    monkeypatch.setattr(monitor, "settings", Settings(_env_file=None, docker_name_filter="nomatch"))
    assert monitor.in_scope("pi1/loki", {"loki"})
    assert monitor.in_scope("pi1/loki", {"pi1/loki"})
    assert not monitor.in_scope("pi1/loki", {"pi2/loki"})


def _prom(values: dict[str, dict[str, float]]):
    """A prometheus.query stand-in answering each node query with ``values[column]``."""
    by_query = {q: values.get(col, {}) for col, q in nodes.QUERIES.items()}

    async def query(promql):
        result = [{"metric": {"node": n}, "value": [0, str(v)]} for n, v in by_query[promql].items()]
        return {"status": "success", "data": {"result": result}}

    return query


def test_node_rows_join_docker_and_metrics(cluster, monkeypatch):
    monkeypatch.setattr(settings, "prometheus_url", "http://prom:9090")
    monkeypatch.setattr(
        nodes.docker,
        "containers_by_node",
        AsyncMock(return_value={"ctl": [{"State": "running"}, {"State": "exited"}], "pi1": None}),
    )
    monkeypatch.setattr(
        nodes.prometheus,
        "query",
        _prom({"up": {"ctl": 1, "pi1": 0, "jetson": 1}, "undervoltage": {"ctl": 1}, "temperature_c": {"ctl": 61.234}}),
    )
    rows = {r["name"]: r for r in asyncio.run(nodes.node_rows())}
    assert list(rows) == ["ctl", "pi1", "jetson"]  # NODES order, then nodes only Prometheus knows
    assert rows["ctl"]["running"] == 1 and rows["ctl"]["containers"] == 2 and not rows["ctl"]["down"]
    assert rows["ctl"]["temperature_c"] == 61.2
    assert rows["pi1"]["down"] and rows["pi1"]["docker_reachable"] is False
    assert rows["jetson"]["docker_reachable"] is None and not rows["jetson"]["down"]
    text = asyncio.run(nodes.list_nodes.ainvoke({}))
    assert "`pi1`: DOWN" in text and "UNDERVOLTAGE" in text


def test_without_prometheus_a_node_is_down_when_docker_is_unreachable():
    assert nodes.is_down({"up": None, "docker_reachable": False})
    assert not nodes.is_down({"up": None, "docker_reachable": True})
    assert not nodes.is_down({"up": True, "docker_reachable": False})


def test_node_tools_are_offered_only_on_a_cluster(cluster, monkeypatch):
    assert "list_nodes" in [t.name for t in configured_tools()]
    monkeypatch.setattr(settings, "nodes", "")
    assert "list_nodes" not in [t.name for t in configured_tools()]


def test_monitor_alerts_once_when_a_node_goes_down(monkeypatch):
    monkeypatch.setattr(
        monitor, "settings", Settings(_env_file=None, nodes="pi1=h", discord_alert_channel_id=1, discord_status_channel_id=2)
    )
    send = AsyncMock()
    monkeypatch.setattr(monitor.discord_alert, "send_alert", send)
    events = []
    monkeypatch.setattr(monitor, "record_event", lambda *a: events.append(a))
    monitor._node_state.clear()

    for down in (False, True, True, False):
        monkeypatch.setattr(monitor.nodes, "node_rows", AsyncMock(return_value=[{"name": "pi1", "down": down}]))
        asyncio.run(monitor._poll_nodes(MagicMock()))

    assert events == [("pi1", "node", "down"), ("pi1", "node", "up")]
    assert [c.kwargs["title"] for c in send.call_args_list] == ["Node down", "Node up"]
