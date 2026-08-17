"""Tests for separator-agnostic service/container name matching."""

import asyncio
from unittest.mock import AsyncMock, patch

from agent.normalize import normalize
from agent.tools import docker


def test_normalize_collapses_separators():
    assert normalize("agent_api") == "agentapi"
    assert normalize("agent-api") == "agentapi"
    assert normalize("agent api") == "agentapi"
    assert normalize("AGENT.API") == "agentapi"
    assert normalize("marconi-agent-api") == "marconiagentapi"


def test_find_container_matches_across_separators():
    fake = [{"Id": "x", "Names": ["/marconi-agent-api"], "State": "running"}]
    with patch("agent.tools.docker.list_containers", new=AsyncMock(return_value=fake)):
        result = asyncio.run(docker.find_container("agent_api"))
    assert result is not None
    assert result["Id"] == "x"


def test_find_container_returns_none_when_no_match():
    with patch("agent.tools.docker.list_containers", new=AsyncMock(return_value=[])):
        assert asyncio.run(docker.find_container("agent_api")) is None
