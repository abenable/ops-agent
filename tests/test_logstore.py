"""Tests for container_logs since/timestamps params and the logstore
collector + reader (cursor-based, plain ``.log``, per-day)."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from agent.logstore import collector, reader


# ---------------------------------------------------------------- container_logs

def test_container_logs_since_forces_tail_all_and_adds_timestamps():
    """A `since` cursor must force tail='all' and pass timestamps through."""
    from agent.tools import docker

    fake = AsyncMock()
    fake.raise_for_status = lambda: None
    fake.text = ""
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=fake)

    with patch("agent.tools.docker._docker_client", return_value=client):
        asyncio.run(docker.container_logs("cid", since="2026-08-09T00:00:00Z", timestamps=True))

    params = client.get.call_args.kwargs["params"]
    assert params["since"] == "2026-08-09T00:00:00Z"
    assert params["tail"] == "all"
    assert params["timestamps"] == "true"


def test_container_logs_default_tail_preserved_without_since():
    from agent.tools import docker

    fake = AsyncMock()
    fake.raise_for_status = lambda: None
    fake.text = ""
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=fake)

    with patch("agent.tools.docker._docker_client", return_value=client):
        asyncio.run(docker.container_logs("cid", tail=50))

    params = client.get.call_args.kwargs["params"]
    assert params["tail"] == 50
    assert "since" not in params
    assert "timestamps" not in params


# ---------------------------------------------------------------- logstore

@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    """Point collector + reader at a tmp data dir and a fresh cursor file."""
    log_root = tmp_path / "logs"
    monkeypatch.setattr(collector, "LOG_ROOT", log_root)
    monkeypatch.setattr(collector, "CURSORS_PATH", tmp_path / "log_cursors.json")
    return log_root


def _watched(names):
    """Patch list_watched_containers to return *names*."""
    return patch("agent.logstore.collector.list_watched_containers", return_value=list(names))


def test_parse_level_prefix_and_keyword_and_raw():
    assert collector._parse_level("ERROR connection refused") == "error"
    assert collector._parse_level("WARN slow query") == "warn"
    assert collector._parse_level("INFO handled request") == "info"
    assert collector._parse_level("DEBUG x=1") == "debug"
    assert collector._parse_level("something failed: connection timeout") == "error"
    assert collector._parse_level("just a normal line") == "raw"


def test_collect_once_appends_new_lines_and_advances_cursor(isolated_store):
    ts1 = "2026-08-09T14:20:00Z"
    ts2 = "2026-08-09T14:20:05Z"
    raw = f"\x01\x00\x00\x00\x00\x00\x00\x05{ts1} ERROR db timeout\n{ts2} WARN slow\n"

    with _watched(["worker"]), patch(
        "agent.logstore.collector.docker.find_container",
        new=AsyncMock(return_value={"Id": "cid1"}),
    ), patch(
        "agent.logstore.collector.docker.container_logs",
        new=AsyncMock(return_value=raw),
    ):
        summary = asyncio.run(collector.collect_once())

    assert summary == {"worker": 2}
    day_file = isolated_store / "worker" / "2026-08-09.log"
    assert day_file.exists()
    content = day_file.read_text(encoding="utf-8").splitlines()
    assert content == [f"{ts1} ERROR db timeout", f"{ts2} WARN slow"]
    recs = list(reader.iter_lines_for_day("worker", "2026-08-09"))
    assert recs[0]["level"] == "error"
    assert recs[0]["raw"] == "ERROR db timeout"
    assert recs[1]["level"] == "warn"
    cursors = json.loads((isolated_store.parent / "log_cursors.json").read_text())
    assert cursors["worker"] == ts2


def test_collect_once_cursor_prevents_duplicate_fetch(isolated_store):
    """Second run with the saved cursor passes it to container_logs and pulls 0 new."""
    raw_first = "2026-08-09T14:20:00Z ERROR boom\n"
    logs = AsyncMock(side_effect=[raw_first, ""])

    with _watched(["worker"]), patch(
        "agent.logstore.collector.docker.find_container",
        new=AsyncMock(return_value={"Id": "cid1"}),
    ), patch("agent.logstore.collector.docker.container_logs", new=logs):
        asyncio.run(collector.collect_once())
        # cursor now stored
        assert json.loads((isolated_store.parent / "log_cursors.json").read_text())["worker"] == "2026-08-09T14:20:00Z"
        summary = asyncio.run(collector.collect_once())

    # second call must have passed since= the stored cursor
    second_call_kwargs = logs.await_args_list[1].kwargs
    assert second_call_kwargs.get("since") == "2026-08-09T14:20:00Z"
    assert second_call_kwargs.get("timestamps") is True
    assert summary == {"worker": 0}


def test_collect_once_skips_unfindable_container_unchanged_cursor(isolated_store):
    with _watched(["ghost"]), patch(
        "agent.logstore.collector.docker.find_container", new=AsyncMock(return_value=None)
    ):
        summary = asyncio.run(collector.collect_once())
    assert summary == {}
    # no cursor file written for a container that was never found
    assert not (isolated_store.parent / "log_cursors.json").exists()


def test_reader_iter_lines_filters_by_time(isolated_store):
    # write two days of records directly as plain <ts> <message> lines
    (isolated_store / "api").mkdir(parents=True)
    (isolated_store / "api" / "2026-08-09.log").write_text(
        "2026-08-09T10:00:00Z a\n2026-08-09T22:00:00Z b\n", encoding="utf-8",
    )
    (isolated_store / "api" / "2026-08-10.log").write_text(
        "2026-08-10T08:00:00Z c\n", encoding="utf-8",
    )
    since = datetime(2026, 8, 9, 20, 0, tzinfo=timezone.utc)
    recs = list(reader.iter_lines("api", since=since))
    assert [r["raw"] for r in recs] == ["b", "c"]


def test_reader_iter_lines_for_day_and_line_count(isolated_store):
    (isolated_store / "api").mkdir(parents=True)
    (isolated_store / "api" / "2026-08-09.log").write_text(
        "2026-08-09T10:00:00Z a\n2026-08-09T11:00:00Z b\n", encoding="utf-8",
    )
    assert reader.line_count("api", "2026-08-09") == 2
    assert reader.line_count("api", "2026-08-10") == 0
    assert [r["raw"] for r in reader.iter_lines_for_day("api", "2026-08-09")] == ["a", "b"]
    assert list(reader.iter_lines_for_day("api", "2026-08-10")) == []


def test_reader_missing_container_yields_nothing(isolated_store):
    assert list(reader.iter_lines("never")) == []


# ---------------------------------------------------------------- tools/logs middle fallback

def test_get_recent_logs_jsonl_middle_fallback(isolated_store, monkeypatch):
    """Loki empty + store has data → JSONL store serves (Docker never hit)."""
    import json as _json
    from agent.tools import logs as logs_mod
    from agent.tools.sources import loki as loki_mod

    root = isolated_store / "svc"
    root.mkdir(parents=True)
    (root / "2026-08-09.log").write_text(
        "2026-08-09T10:00:00Z ERROR stored boom\n", encoding="utf-8",
    )
    # Loki returns empty (no result), Docker must NOT be reached.
    monkeypatch.setattr(logs_mod, "format_loki", lambda *a, **k: "")
    monkeypatch.setattr(loki_mod, "query_loki_range", AsyncMock(return_value={"data": {"result": []}}))
    monkeypatch.setattr("agent.storage.repository.list_watched_containers", lambda: ["svc"])
    from agent.tools.logs import get_recent_logs
    out = asyncio.run(get_recent_logs("svc", lines=10))
    assert "stored boom" in out
    assert "[2026-08-09T10:00:00Z]" in out
