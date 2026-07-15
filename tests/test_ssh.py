"""Tests for SSH-based tools."""

import asyncio

from agent.tools.ssh import run_ssh_command


def test_ssh_command_returns_result_shape():
    result = asyncio.run(run_ssh_command("127.0.0.1", "echo hello"))
    assert result["host"] == "127.0.0.1"
    assert "returncode" in result
    assert "stdout" in result
    assert "stderr" in result
