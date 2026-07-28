"""Tests for separator-agnostic service/container name matching."""

import asyncio
from unittest.mock import patch

from agent.tools import docker
from agent.tools.normalize import normalize, regex_parts


def test_normalize_collapses_separators():
    assert normalize("agent_api") == "agentapi"
    assert normalize("agent-api") == "agentapi"
    assert normalize("agent api") == "agentapi"
    assert normalize("AGENT.API") == "agentapi"
    assert normalize("marconi-agent-api") == "marconiagentapi"


def test_regex_parts_separator_agnostic():
    assert regex_parts("agent_api") == "agent.*api"
    assert regex_parts("marconi-agent-api") == "marconi.*agent.*api"
    assert regex_parts("api") == "api"


def test_regex_parts_matches_real_container_name():
    # A user typing 'agent_api' should produce a regex that matches 'marconi-agent-api'.
    import re

    assert re.search(regex_parts("agent_api"), "marconi-agent-api")


def test_find_container_matches_across_separators():
    from unittest.mock import AsyncMock

    fake = [{"Id": "x", "Names": ["/marconi-agent-api"], "State": "running"}]
    with patch("agent.tools.docker.list_containers", new=AsyncMock(return_value=fake)):
        result = asyncio.run(docker.find_container("agent_api"))
    assert result is not None
    assert result["Id"] == "x"


def test_find_container_returns_none_when_no_match():
    from unittest.mock import AsyncMock

    with patch("agent.tools.docker.list_containers", new=AsyncMock(return_value=[])):
        assert asyncio.run(docker.find_container("agent_api")) is None
