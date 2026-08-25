"""Tests for the scheduled daily/weekly infrastructure digests."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from agent.bot import digest
from agent.watchlist.repository import events_since, record_event

_MONDAY = datetime(2026, 8, 17, 5, 0, tzinfo=UTC)


@pytest.fixture
def quiet_infra(monkeypatch):
    """No containers, no endpoints — leaves the event log as the only content."""
    monkeypatch.setattr(digest.docker, "list_containers", AsyncMock(return_value=[]))
    monkeypatch.setattr(digest, "get_monitored_endpoints", dict)
    monkeypatch.setattr(digest, "list_watched_containers", list)
    monkeypatch.setattr(digest, "clean", AsyncMock(return_value="Everything looks fine."))


@pytest.fixture
def sent(monkeypatch):
    """Capture (title, chunks) of every report posted."""
    posted: list[tuple[str, list[str]]] = []

    async def _capture(_channel, title, chunks, _bot):
        posted.append((title, chunks))

    monkeypatch.setattr(digest.discord_alert, "post_report", _capture)
    monkeypatch.setattr(digest.settings, "discord_reports_channel_id", 123)
    return posted


def test_daily_reports_no_changes_when_nothing_happened(quiet_infra):
    body = asyncio.run(digest.build_daily(_MONDAY))
    assert "- no changes" in body


def test_daily_lists_transitions_from_the_last_day(quiet_infra):
    record_event("marconi-agent-api", "container", "down")
    record_event("marconi-agent-api", "container", "up")
    body = asyncio.run(digest.build_daily())
    assert body.count("`marconi-agent-api`") == 2
    assert "down" in body and "up" in body


def test_weekly_pairs_events_into_outage_counts_and_downtime():
    events = [
        {"target": "api", "kind": "container", "state": "down", "at": "2026-08-11 10:00:00"},
        {"target": "api", "kind": "container", "state": "up", "at": "2026-08-11 10:30:00"},
        {"target": "api", "kind": "container", "state": "down", "at": "2026-08-12 09:00:00"},
        {"target": "api", "kind": "container", "state": "up", "at": "2026-08-12 11:15:00"},
    ]
    stats = digest._downtime(events)
    assert stats["api"]["outages"] == 2
    assert digest._duration(stats["api"]["downtime"]) == "2h45m"  # 30m + 2h15m
    assert "still_down" not in stats["api"]


def test_weekly_counts_an_unclosed_outage_as_still_down():
    down_at = datetime.now(UTC) - timedelta(hours=2)
    events = [
        {
            "target": "web",
            "kind": "endpoint",
            "state": "down",
            "at": down_at.strftime("%Y-%m-%d %H:%M:%S"),
        }
    ]
    stats = digest._downtime(events)
    assert stats["web"]["still_down"] is True
    assert stats["web"]["downtime"] >= timedelta(hours=2)


def test_weekly_asks_the_agent_about_a_flapping_target(quiet_infra, monkeypatch):
    for _ in range(digest._FLAP_THRESHOLD):
        record_event("marconi-agent-api", "container", "down")
        record_event("marconi-agent-api", "container", "up")

    asked: list[str] = []

    async def _fake_investigate(question, thread_id=None):
        asked.append(question)
        return "It runs out of memory."

    monkeypatch.setattr("agent.workflows.investigate.investigate", _fake_investigate)
    body = asyncio.run(digest.build_weekly())

    assert "**Why**" in body
    assert "It runs out of memory." in body
    assert "marconi-agent-api" in asked[0]


def test_weekly_skips_the_narrative_when_nothing_flapped(quiet_infra):
    record_event("marconi-agent-api", "container", "down")
    body = asyncio.run(digest.build_weekly())
    assert "**Why**" not in body
    assert "down 1×" in body


def test_tick_posts_weekly_only_on_the_configured_weekday(quiet_infra, sent, monkeypatch):
    monkeypatch.setattr(digest.settings, "weekly_report_weekday", 0)

    asyncio.run(digest.run_tick(None, _MONDAY))
    assert [t.split(" —")[0] for t in (title for title, _ in sent)] == [
        "Daily report",
        "Weekly report",
    ]

    sent.clear()
    asyncio.run(digest.run_tick(None, _MONDAY + timedelta(days=1)))
    assert [title.split(" —")[0] for title, _ in sent] == ["Daily report"]


def test_nothing_is_posted_without_a_reports_channel(quiet_infra, sent, monkeypatch):
    monkeypatch.setattr(digest.settings, "discord_reports_channel_id", None)
    asyncio.run(digest.run_tick(None, _MONDAY))
    assert sent == []


def test_events_since_ignores_anything_before_the_cutoff():
    record_event("api", "container", "down")
    assert events_since(datetime.now(UTC) - timedelta(minutes=5)) != []
    assert events_since(datetime.now(UTC) + timedelta(minutes=5)) == []


def test_posting_a_report_sends_its_body_to_the_reports_channel(quiet_infra, sent):
    asyncio.run(digest.post(None, "daily", _MONDAY))
    assert sent and "no changes" in sent[0][1][0]
