"""Tests for Docker tools."""

import asyncio
import os
from unittest.mock import patch

from agent.tools.docker import list_containers


def test_list_containers_returns_empty_without_socket():
    with patch("os.path.exists", return_value=False):
        result = asyncio.run(list_containers())
    assert result == []


def test_docker_available_with_tcp_host():
    with patch.dict(os.environ, {"DOCKER_HOST": "tcp://localhost:2375"}):
        from agent.tools.docker import _docker_available

        assert _docker_available() is True
