"""Tests for separator-agnostic service/container name matching."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from agent.normalize import AmbiguousName, normalize
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


def test_find_container_rejects_an_ambiguous_partial_name():
    fake = [
        {"Id": "b", "Names": ["/marconi-api-gateway"], "State": "running"},
        {"Id": "a", "Names": ["/marconi-agent-api"], "State": "running"},
    ]
    with (
        patch("agent.tools.docker.list_containers", new=AsyncMock(return_value=fake)),
        pytest.raises(AmbiguousName) as caught,
    ):
        asyncio.run(docker.find_container("api"))
    assert caught.value.matches == ["marconi-agent-api", "marconi-api-gateway"]


def test_find_container_prefers_an_exact_name_over_a_substring():
    fake = [
        {"Id": "long", "Names": ["/marconi-agent-api-worker"], "State": "running"},
        {"Id": "exact", "Names": ["/agent_api"], "State": "running"},
    ]
    with patch("agent.tools.docker.list_containers", new=AsyncMock(return_value=fake)):
        result = asyncio.run(docker.find_container("agent-api"))
    assert result["Id"] == "exact"


def test_docker_status_reports_ambiguity_instead_of_guessing():
    fake = [
        {"Id": "a", "Names": ["/marconi-agent-api"], "State": "running"},
        {"Id": "b", "Names": ["/marconi-api-gateway"], "State": "exited"},
    ]
    with patch("agent.tools.docker.list_containers", new=AsyncMock(return_value=fake)):
        out = asyncio.run(docker.docker_status.ainvoke({"container": "api"}))
    assert "matches 2 containers" in out
    assert "marconi-agent-api" in out and "marconi-api-gateway" in out


def test_watch_list_lookup_rejects_an_ambiguous_partial_name(tmp_database):
    from agent.watchlist.repository import (
        add_watched_container,
        find_watched_container,
        remove_watched_container,
    )

    add_watched_container("marconi-agent-api")
    add_watched_container("marconi-api-gateway")

    with pytest.raises(AmbiguousName) as caught:
        find_watched_container("api")
    assert caught.value.matches == ["marconi-agent-api", "marconi-api-gateway"]

    # An unambiguous partial still resolves, and an exact name never goes fuzzy.
    assert find_watched_container("gateway") == "marconi-api-gateway"
    assert remove_watched_container("marconi-agent-api") is True
