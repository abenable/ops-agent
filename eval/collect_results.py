"""Turn the transcripts in eval/logs/ into tracked results under eval/results/.

The transcripts hold everything a run did; this pulls out the numbers we track
(latency, tokens, tool calls, retries) and writes one CSV row per run plus a
per-notebook summary. Run it after executing a notebook.
"""

import csv
import json
import shutil
import statistics
import sys
from collections import defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
LOG_DIR = _HERE / "logs"
RESULTS_DIR = _HERE / "results"

FIELDS = [
    "label", "suite", "section", "model", "verdict", "missing",
    "empty_answer", "finish_reason", "truncated",
    "turns", "tool_calls", "tool_calls_requested", "retries", "tool_failures",
    "tools_called", "input_tokens", "output_tokens", "total_tokens",
    "duration_ms", "slowest_call_ms", "error", "file",
]


def _retries(calls: list[dict]) -> tuple[int, int]:
    """Repeated identical tool calls, and tool results that came back as failures.

    The loop answers a repeat of an already-failed call with a message saying so,
    so a duplicate (name, args) pair is the model retrying rather than new work.
    """
    seen: set[tuple[str, str]] = set()
    repeats = 0
    failures = 0
    for call in calls:
        for result in call.get("tool_results") or []:
            key = (result["name"], json.dumps(result.get("args"), sort_keys=True, default=str))
            if key in seen:
                repeats += 1
            seen.add(key)
            text = str(result.get("result", ""))
            if text.startswith("(tool call failed") or "already failed" in text:
                failures += 1
    return repeats, failures


def row_from(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    label = data.get("label", path.stem)
    suite = label.split(":")[0]
    section = label.split(":", 1)[1].split("#")[0] if ":" in label else ""
    grade = data.get("grade") or {}
    usage = data.get("total_usage") or {}
    calls = data.get("calls") or []
    repeats, failures = _retries(calls)
    durations = [c["duration_ms"] for c in calls if c.get("duration_ms") is not None]
    reasons = [
        (c.get("response") or {}).get("finish_reason")
        for c in calls
        if (c.get("response") or {}).get("finish_reason")
    ]
    truncated = "length" in reasons

    passed = grade.get("passed")
    missing = "; ".join(
        (grade.get("missing") or []) + [f"tool:{t}" for t in (grade.get("missing_tools") or [])]
    )
    return {
        "label": label,
        "suite": suite,
        "section": section,
        "model": data.get("model", ""),
        "verdict": "-" if passed is None else ("PASS" if passed else "FAIL"),
        "missing": missing,
        "empty_answer": grade.get("empty_answer"),
        "finish_reason": ";".join(dict.fromkeys(reasons)),
        "truncated": truncated,
        "turns": len(calls),
        "tool_calls": data.get("tool_calls"),
        "tool_calls_requested": data.get("tool_calls_requested"),
        "retries": repeats,
        "tool_failures": failures,
        "tools_called": ",".join(data.get("tool_names") or []),
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
        "duration_ms": data.get("duration_ms"),
        "slowest_call_ms": max(durations) if durations else 0,
        "error": data.get("error") or "",
        "file": path.name,
    }


def _summary(rows: list[dict]) -> dict:
    graded = [r for r in rows if r["verdict"] != "-"]
    passed = [r for r in graded if r["verdict"] == "PASS"]
    dur = [r["duration_ms"] for r in rows if r["duration_ms"]]
    tok = [r["total_tokens"] for r in rows]
    return {
        "runs": len(rows),
        "graded": len(graded),
        "passed": len(passed),
        "pass_rate": round(len(passed) / len(graded), 3) if graded else None,
        "tool_calls_total": sum(r["tool_calls"] or 0 for r in rows),
        "retries_total": sum(r["retries"] for r in rows),
        "tool_failures_total": sum(r["tool_failures"] for r in rows),
        "empty_answers": sum(1 for r in rows if r["empty_answer"]),
        "truncated_runs": sum(1 for r in rows if r["truncated"]),
        "tokens_total": sum(tok),
        "tokens_mean": round(statistics.mean(tok)) if tok else 0,
        "latency_ms_mean": round(statistics.mean(dur)) if dur else 0,
        "latency_ms_median": round(statistics.median(dur)) if dur else 0,
        "latency_ms_max": max(dur) if dur else 0,
    }


def _transcript_name(label: str) -> str:
    """A readable filename from a run label: suite:section#n -> section__runN.json."""
    section = label.split(":", 1)[1] if ":" in label else label
    section, _, run = section.partition("#")
    return f"{section or 'run'}__run{run or '1'}.json"


def _copy_transcripts(folder: Path, rows: list[dict]) -> None:
    """Place each run's transcript beside its suite's summary, named by section."""
    dest = folder / "transcripts"
    dest.mkdir(parents=True, exist_ok=True)
    for row in rows:
        src = LOG_DIR / row["file"]
        if src.exists():
            shutil.copy2(src, dest / _transcript_name(row["label"]))


README = """# Eval results

Generated by `eval/collect_results.py` from the transcripts in `eval/logs/`.

## Layout

    all_runs.csv              one row per run, every suite
    index.json                per-suite and overall aggregates
    <suite>/runs.csv          that suite's runs
    <suite>/summary.json      that suite's aggregates, split by section
    <suite>/transcripts/      the full transcript behind each run

Transcripts are named `<section>__run<N>.json`, where section is one of:

    live-inscope       question the bound tools can answer
    live-outofscope    question needing a tool that was deliberately withheld
    eval               question against the offline dataset in data/eval/

## Columns in runs.csv

    verdict                   PASS / FAIL / - (ungraded)
    missing                   what the grader did not find: text, or tool:<name>
    empty_answer              the run produced no answer at all (always a FAIL)
    finish_reason             why each model call stopped; "length" means truncated
    truncated                 True when any call hit the token ceiling
    turns                     model calls in the run
    tool_calls                tools actually executed
    tool_calls_requested      tools the model asked for (higher = some refused)
    retries                   repeated identical tool calls
    tool_failures             tool results that came back as errors
    input/output/total_tokens reported by the model endpoint
    duration_ms               wall clock for the whole run
    slowest_call_ms           the single slowest model call in the run
"""


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def collect() -> list[dict]:
    rows = [r for r in (row_from(p) for p in sorted(LOG_DIR.glob("*.json"))) if r]
    if not rows:
        print(f"no transcripts in {LOG_DIR}")
        return []

    by_suite: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_suite[r["suite"]].append(r)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    _write_csv(RESULTS_DIR / "all_runs.csv", rows)

    (RESULTS_DIR / "README.md").write_text(README)

    index = {}
    for suite, suite_rows in sorted(by_suite.items()):
        folder = RESULTS_DIR / suite
        _write_csv(folder / "runs.csv", suite_rows)
        _copy_transcripts(folder, suite_rows)
        summary = _summary(suite_rows)
        by_section = {
            sec: _summary([r for r in suite_rows if r["section"] == sec])
            for sec in sorted({r["section"] for r in suite_rows})
        }
        (folder / "summary.json").write_text(
            json.dumps({"suite": suite, **summary, "sections": by_section}, indent=2) + "\n"
        )
        index[suite] = summary

    (RESULTS_DIR / "index.json").write_text(
        json.dumps({"suites": index, "overall": _summary(rows)}, indent=2) + "\n"
    )
    return rows


def report(rows: list[dict]) -> None:
    print(f"{'label':<40}{'verdict':<9}{'tools':<7}{'retry':<7}{'tokens':<9}{'ms':<8}")
    print("-" * 80)
    for r in rows:
        print(f"{r['label'][:39]:<40}{r['verdict']:<9}{r['tool_calls'] or 0:<7}"
              f"{r['retries']:<7}{r['total_tokens']:<9}{r['duration_ms'] or 0:<8}")
    s = _summary(rows)
    print("-" * 80)
    print(f"graded {s['passed']}/{s['graded']} passed  |  "
          f"{s['tool_calls_total']} tool calls, {s['retries_total']} retries, "
          f"{s['tool_failures_total']} tool failures")
    if s["empty_answers"] or s["truncated_runs"]:
        print(f"  {s['empty_answers']} empty answer(s), "
              f"{s['truncated_runs']} truncated at the token ceiling")
    print(f"tokens {s['tokens_total']} total, {s['tokens_mean']} mean  |  "
          f"latency mean {s['latency_ms_mean']}ms, median {s['latency_ms_median']}ms, "
          f"max {s['latency_ms_max']}ms")
    print(f"\nwritten to {RESULTS_DIR}")


if __name__ == "__main__":
    collected = collect()
    if collected:
        report(collected)
    sys.exit(0 if collected else 1)
