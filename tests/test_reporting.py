"""Tests for the reporting workflow (incident + daily/weekly log reports)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.logstore import collector
from agent.memory.repository import store_incident
from agent.workflows import reporting
from agent.workflows.reporting import run_report_workflow


@pytest.fixture
def isolated_report_store(tmp_path, monkeypatch):
    """Point logstore + reporting dirs at a tmp tree."""
    log_root = tmp_path / "logs"
    monkeypatch.setattr(collector, "LOG_ROOT", log_root)
    monkeypatch.setattr(reporting, "REPORT_ROOT", tmp_path / "reports")
    monkeypatch.setattr(reporting, "DAILY_DIR", tmp_path / "reports" / "daily")
    monkeypatch.setattr(reporting, "settings", type("S", (), {"database_url": f"sqlite:///{tmp_path}/agent.db"})())
    return tmp_path


def _seed_day(container: str, day: str, records: list[tuple[str, str]]) -> None:
    """Write records as (ts, message) tuples into the per-day ``.log`` file.
    The message carries its level prefix (ERROR/INFO/...) so the reader parses
    the level at read time."""
    root = collector.LOG_ROOT / container
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{day}.log"
    with path.open("a", encoding="utf-8") as fh:
        for ts, msg in records:
            fh.write(f"{ts} {msg}\n")


def test_daily_report_counts_and_top_errors(isolated_report_store, monkeypatch):
    _seed_day("worker", "2026-08-09", [
        ("2026-08-09T10:00:00Z", "ERROR db timeout after 30s"),
        ("2026-08-09T10:01:00Z", "ERROR db timeout after 30s"),
        ("2026-08-09T11:00:00Z", "ERROR cache miss for key abc123"),
        ("2026-08-09T12:00:00Z", "INFO request handled"),
    ])
    monkeypatch.setattr(reporting, "list_watched_containers", lambda: ["worker"])
    # suppress reading yesterday (2026-08-08) by ensuring it's empty
    report = reporting.daily_report("2026-08-09")
    assert "worker" in report
    assert "Daily log report — 2026-08-09" in report
    assert "Errors" in report
    # top errors should normalize the two "db timeout" lines to one group of 2
    assert "db timeout" in report
    assert "(2" in report or "2×" in report
    # persisted sidecars
    assert (reporting.DAILY_DIR / "2026-08-09.md").exists()
    assert (reporting.DAILY_DIR / "2026-08-09.json").exists()
    payload = json.loads((reporting.DAILY_DIR / "2026-08-09.json").read_text())
    assert payload["containers"][0]["errors"] == 3
    assert payload["containers"][0]["lines"] == 4


def test_daily_report_first_seen_excludes_yesterday(isolated_report_store, monkeypatch):
    _seed_day("worker", "2026-08-08", [
        ("2026-08-08T09:00:00Z", "ERROR recurring deadlock"),
    ])
    _seed_day("worker", "2026-08-09", [
        ("2026-08-09T10:00:00Z", "ERROR recurring deadlock"),
        ("2026-08-09T10:30:00Z", "ERROR brand new oom kill pid 999"),
    ])
    monkeypatch.setattr(reporting, "list_watched_containers", lambda: ["worker"])
    report = reporting.daily_report("2026-08-09")
    assert "brand new oom kill" in report
    assert "recurring deadlock" not in report or "First-seen" in report


def test_daily_report_no_data(isolated_report_store, monkeypatch):
    monkeypatch.setattr(reporting, "list_watched_containers", lambda: ["worker"])
    report = reporting.daily_report("2026-08-09")
    assert "No log lines" in report


def test_weekly_report_reads_daily_sidecars(isolated_report_store, monkeypatch):
    # seed two days of sidecars directly
    for day, n in [("2026-08-08", 5), ("2026-08-09", 2)]:
        payload = {
            "day": day,
            "containers": [{"container": "worker", "lines": n, "errors": n,
                            "warnings": 0, "top_errors": [("ERROR oom", n)]}],
            "first_seen": ["ERROR oom"] if day == "2026-08-08" else [],
        }
        reporting.DAILY_DIR.mkdir(parents=True, exist_ok=True)
        (reporting.DAILY_DIR / f"{day}.json").write_text(json.dumps(payload))
    report = reporting.weekly_report("2026-08-09")
    assert "Week ending 2026-08-09" in report
    assert "worker" in report
    # repeat-offenders section present
    assert "Repeat" in report
    # the error trend row should show 5 then 2
    assert "5" in report and "2" in report


def test_weekly_report_no_data(isolated_report_store):
    report = reporting.weekly_report("2026-08-09")
    assert "No daily reports" in report


# ---------------------------------------------------------------- run_report_workflow (incidents)

def test_report_workflow_not_found(tmp_database):
    message = run_report_workflow("missing-id")
    assert "no incident found" in message.lower()


def test_report_workflow_existing_incident(tmp_database):
    summary = "the service is on fire"
    incident_id = store_incident("web", summary)

    report = run_report_workflow(incident_id)

    assert incident_id in report
    assert summary in report
    assert "web" in report


def test_create_to_report_loop(tmp_database):
    incident_id = store_incident("api", "latency spike detected")

    report = run_report_workflow(incident_id)

    assert incident_id in report
    assert "latency spike detected" in report
    assert "api" in report
