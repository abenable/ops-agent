"""Tests for the watch-list repository."""


def test_watch_list_roundtrip(tmp_database):
    from agent.watchlist.repository import (
        add_watched_container,
        list_watched_containers,
        remove_watched_container,
    )

    assert list_watched_containers() == []
    assert add_watched_container("marconi-agent-api") is True
    assert add_watched_container("marconi-agent-api") is False
    assert list_watched_containers() == ["marconi-agent-api"]

    # Separator-agnostic resolution on remove.
    assert remove_watched_container("agent_api") is True
    assert list_watched_containers() == []
    assert remove_watched_container("agent_api") is False


def test_find_watched_container_matches_variants(tmp_database):
    from agent.watchlist.repository import add_watched_container, find_watched_container

    add_watched_container("marconi-agent-api")
    assert find_watched_container("agent_api") == "marconi-agent-api"
    assert find_watched_container("agent-api") == "marconi-agent-api"
    assert find_watched_container("nonexistent") is None
