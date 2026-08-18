"""Shared pytest fixtures and configuration."""

import pytest
from langgraph.checkpoint.memory import InMemorySaver


@pytest.fixture(autouse=True)
def tmp_database(tmp_path, monkeypatch):
    """Point the repository and the conversation checkpointer at a temp file.

    Autouse: the monitor writes transition events during its tests and the
    agent checkpoints its threads, and no test should ever touch the real
    database. ``_CHECKPOINTER`` is reset so it is rebuilt against this path
    rather than reused from a previous test.
    """
    import agent.engine as engine
    import agent.memory as memory
    import agent.watchlist.repository as repo

    test_path = tmp_path / "agent.db"
    monkeypatch.setattr(repo, "DB_PATH", test_path)
    monkeypatch.setattr(memory, "DB_PATH", test_path)
    # Conversation memory runs on an InMemorySaver here: tests drive their own
    # event loop per test, and the real saver's connection would have to be
    # closed inside each one or the process hangs at exit. Persistence itself
    # is covered by test_memory_persists_across_connections.
    monkeypatch.setattr(memory, "_CHECKPOINTER", InMemorySaver())
    monkeypatch.setattr(engine, "_GRAPH", None)
    return test_path
