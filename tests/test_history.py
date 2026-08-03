"""Tests for the per-channel conversation history helper."""

import agent.bot.history as history


def test_empty_history_returns_empty_string(tmp_database):
    assert history.format_history(123) == ""
    assert history.get_history(123) == []


def test_history_records_and_formats_turns(tmp_database):
    history.add_message(1, "user", "status of containers")
    history.add_message(1, "assistant", "marconi-agent-web is running")

    turns = history.get_history(1)
    assert len(turns) == 2
    assert turns[0]["role"] == "user"
    assert turns[1]["content"] == "marconi-agent-web is running"

    formatted = history.format_history(1)
    assert "User: status of containers" in formatted
    assert "Oracle: marconi-agent-web is running" in formatted


def test_history_is_isolated_by_channel(tmp_database):
    history.add_message(7, "user", "channel seven")
    history.add_message(8, "user", "channel eight")

    assert history.format_history(7) == "User: channel seven"
    assert history.format_history(8) == "User: channel eight"


def test_history_respects_limit(tmp_database):
    for i in range(5):
        history.add_message(2, "user", f"msg {i}")
    assert len(history.get_history(2)) == 5
    assert len(history.get_history(2, limit=2)) == 2
    # limit returns the most recent rows in chronological order
    assert history.get_history(2, limit=2)[0]["content"] == "msg 3"
    assert history.get_history(2, limit=2)[1]["content"] == "msg 4"


def test_history_caps_stored_rows(tmp_database):
    for i in range(25):
        history.add_message(3, "user", f"msg {i}")
    rows = history.get_history(3, limit=100)
    assert len(rows) == 20
    assert rows[-1]["content"] == "msg 24"


def test_long_message_is_shortened(tmp_database):
    big = "x" * 5000
    history.add_message(4, "user", big)
    turns = history.get_history(4)
    assert len(turns[0]["content"]) < 4100
