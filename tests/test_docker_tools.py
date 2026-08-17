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
