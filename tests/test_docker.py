"""Tests for Docker tools."""

import asyncio
import os
from unittest.mock import AsyncMock, Mock, patch

import httpx2 as httpx

from agent.tools.docker import list_containers


def test_list_containers_returns_empty_without_socket():
    with patch("os.path.exists", return_value=False):
        result = asyncio.run(list_containers())
    assert result == []


def test_docker_available_with_tcp_host():
    with patch.dict(os.environ, {"DOCKER_HOST": "tcp://localhost:2375"}):
        from agent.tools.docker import _docker_available

        assert _docker_available() is True


def test_list_containers_parses_response():
    """Regression test that exercises the async unix-socket transport path."""
    fake_response = Mock()
    fake_response.json.return_value = [{"Id": "abc123", "Names": ["/web"]}]

    with patch("agent.tools.docker._docker_available", return_value=True):
        with patch("agent.tools.docker.httpx.AsyncClient") as mock_client_class:
            mock_client = mock_client_class.return_value
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=fake_response)

            result = asyncio.run(list_containers())

    assert result == [{"Id": "abc123", "Names": ["/web"]}]
    transport = mock_client_class.call_args.kwargs.get("transport")
    assert isinstance(transport, httpx.AsyncHTTPTransport)
