"""Tests for the read-only Docker LangChain tools exposed to the agentic loop."""

import asyncio
from unittest.mock import AsyncMock, patch

from agent.tools.docker import docker_logs, docker_status


def _fake_container():
    return {
        "Id": "abc123",
        "Names": ["/marconi-agent-api"],
        "State": "running",
        "Status": "Up 5 minutes",
        "Image": "marconi/agent:latest",
    }


def test_docker_status_returns_state():
    with patch("agent.tools.docker.find_container", new=AsyncMock(return_value=_fake_container())):
        out = asyncio.run(docker_status.ainvoke({"container": "agent_api"}))
    assert "marconi-agent-api" in out
    assert "running" in out
    assert "Up 5 minutes" in out


def test_docker_status_no_match():
    with patch("agent.tools.docker.find_container", new=AsyncMock(return_value=None)):
        out = asyncio.run(docker_status.ainvoke({"container": "nope"}))
    assert "no container" in out


def test_docker_logs_returns_lines():
    with patch("agent.tools.docker.find_container", new=AsyncMock(return_value=_fake_container())), patch(
        "agent.tools.docker.container_logs", new=AsyncMock(return_value="line1\nline2\n")
    ):
        out = asyncio.run(docker_logs.ainvoke({"container": "agent_api", "tail": 5}))
    assert "line1" in out and "line2" in out


def test_docker_logs_caps_tail_at_200():
    captured = {}

    async def fake_logs(container_id, tail=20):
        captured["tail"] = tail
        return "ok"

    with patch("agent.tools.docker.find_container", new=AsyncMock(return_value=_fake_container())), patch(
        "agent.tools.docker.container_logs", new=fake_logs
    ):
        asyncio.run(docker_logs.ainvoke({"container": "agent_api", "tail": 99999}))
    assert captured["tail"] == 200


def test_docker_logs_strips_control_bytes():
    with patch("agent.tools.docker.find_container", new=AsyncMock(return_value=_fake_container())), patch(
        "agent.tools.docker.container_logs", new=AsyncMock(return_value="\x02\x00abc\n")
    ):
        out = asyncio.run(docker_logs.ainvoke({"container": "agent_api", "tail": 5}))
    assert "\x02" not in out
    assert "abc" in out


def test_empty_docker_host_env_falls_back_to_default_socket(monkeypatch):
    """Regression: DOCKER_HOST='' (a common .env/compose placeholder) must behave as unset, not reach the transport layer and kill every Docker call."""
    from agent.tools import docker

    monkeypatch.setenv("DOCKER_HOST", "")
    assert docker._docker_host() == "unix:///var/run/docker.sock"

    monkeypatch.setenv("DOCKER_HOST", "tcp://docker:2375")
    assert docker._docker_host() == "tcp://docker:2375"


def test_unconfigured_backends_are_left_out_of_the_tool_set(monkeypatch):
    """A tool that cannot work is not offered: the model would read its failure
    as the backend being down rather than never configured."""
    from agent.config.settings import settings
    from agent.tools import ALL_TOOLS, configured_tools

    monkeypatch.setattr(settings, "prometheus_url", "http://prom:9090")
    monkeypatch.setattr(settings, "loki_url", "http://loki:3100")
    assert configured_tools() == ALL_TOOLS

    monkeypatch.setattr(settings, "loki_url", "")
    names = [t.name for t in configured_tools()]
    assert "query_loki" not in names
    assert "query_prometheus" in names

    monkeypatch.setattr(settings, "prometheus_url", "")
    assert [t.name for t in configured_tools()] == [
        "list_services",
        "docker_status",
        "docker_logs",
    ]
