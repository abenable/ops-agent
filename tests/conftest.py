"""Shared pytest fixtures and configuration."""

import pytest


@pytest.fixture
def tmp_database(tmp_path, monkeypatch):
    """Point the repository at a temporary SQLite file."""
    import agent.storage.repository as repo

    test_path = tmp_path / "agent.db"
    monkeypatch.setattr(repo, "_DB_PATH", test_path)
    return test_path
