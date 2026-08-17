"""Shared pytest fixtures and configuration."""

import pytest


@pytest.fixture(autouse=True)
def tmp_database(tmp_path, monkeypatch):
    """Point the repository at a temporary SQLite file.

    Autouse: the monitor writes transition events during its tests, and no test
    should ever touch the real database.
    """
    import agent.watchlist.repository as repo

    test_path = tmp_path / "agent.db"
    monkeypatch.setattr(repo, "_DB_PATH", test_path)
    return test_path
