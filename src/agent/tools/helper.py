"""Read-only access to the local eval dataset (data/eval/*.jsonl), built by scripts/build_eval_dataset.sh + scripts/metrics_to_jsonl.py."""

import json
from collections import deque
from pathlib import Path

from langchain_core.tools import tool

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_EVAL_METRICS_PATH = _REPO_ROOT / "data" / "eval" / "combined_metrics.jsonl"
DEFAULT_EVAL_LOGS_PATH = _REPO_ROOT / "data" / "eval" / "combined_logs.jsonl"


def read_eval_metrics(
    metric: str = "",
    machine: str = "",
    limit: int = 50,
    path: Path = DEFAULT_EVAL_METRICS_PATH,
) -> tuple[list[dict], int]:
    """Stream the eval metrics JSONL, filtering by metric-name substring and/or exact machine. Returns (first `limit` matches in file order, total matches)."""
    results: list[dict] = []
    total = 0
    with path.open() as f:
        for line in f:
            if metric and metric not in line:
                continue
            rec = json.loads(line)
            if metric and metric not in rec["metric"]:
                continue
            if machine and rec["labels"].get("machine") != machine:
                continue
            total += 1
            if len(results) < limit:
                results.append(rec)
    return results, total


@tool
def query_eval_metrics(metric: str = "", machine: str = "", limit: int = 20) -> str:
    """Read sample records from the local eval metrics dataset for offline task generation/testing (not live infra). Filter by `metric` name substring and/or `machine` ('marconi-01', 'marconi-02', 'lambda2'). Returns up to `limit` matching JSON records, one per line, earliest first, after a header line giving how many of the total matches you are seeing. If that header says you are seeing a fraction of the matches, treat what you got as a sample and say so rather than describing it as the whole picture."""
    if not DEFAULT_EVAL_METRICS_PATH.exists():
        return f"(eval metrics dataset not found at {DEFAULT_EVAL_METRICS_PATH}; rebuild with scripts/build_eval_dataset.sh)"
    limit = max(1, min(limit, 200))
    records, total = read_eval_metrics(metric=metric, machine=machine, limit=limit)
    if not records:
        return "(no matching records)"
    header = f"(showing {len(records)} of {total} matching samples, earliest first)"
    return "\n".join([header, *(json.dumps(r) for r in records)])


def read_eval_logs(
    contains: str = "",
    machine: str = "",
    level: str = "",
    limit: int = 50,
    path: Path = DEFAULT_EVAL_LOGS_PATH,
) -> tuple[list[dict], int]:
    """Stream the eval logs JSONL, filtering by a substring in the log line, the Promtail-detected level, and/or exact machine. Returns (the newest `limit` matches, total matches)."""
    keep: deque[dict] = deque(maxlen=limit)
    total = 0
    with path.open() as f:
        for line in f:
            if contains and contains not in line:
                continue
            rec = json.loads(line)
            if contains and contains not in rec["line"]:
                continue
            if machine and rec["machine"] != machine:
                continue
            if level and rec["labels"].get("detected_level") != level:
                continue
            total += 1
            keep.append(rec)
    return sorted(keep, key=lambda r: r["timestamp_ns"], reverse=True), total


@tool
def query_eval_logs(
    contains: str = "", machine: str = "", level: str = "", limit: int = 20
) -> str:
    """Read sample records from the local eval logs dataset for offline task generation/testing (not live Loki). Filter by `contains` substring in the log line, `machine` ('marconi-01', 'marconi-02', 'lambda2'), and/or `level` (the Promtail-detected level: 'error', 'warn', 'info', 'unknown') — prefer `level='error'` over guessing at spellings of the word in the text. Returns up to `limit` matching JSON records, newest first, one per line, after a header line giving how many of the total matches you are seeing. If that header says you are seeing a fraction of the matches, treat what you got as a sample and say so rather than describing it as the whole picture."""
    if not DEFAULT_EVAL_LOGS_PATH.exists():
        return f"(eval logs dataset not found at {DEFAULT_EVAL_LOGS_PATH}; rebuild with scripts/build_eval_dataset.sh)"
    limit = max(1, min(limit, 200))
    records, total = read_eval_logs(contains=contains, machine=machine, level=level, limit=limit)
    if not records:
        return "(no matching records)"
    header = f"(showing {len(records)} of {total} matching log lines, newest first)"
    return "\n".join([header, *(json.dumps(r) for r in records)])


def _selftest() -> None:
    import tempfile

    metric_lines = [
        {"metric": "up", "labels": {"machine": "marconi-01"}, "value": 1.0, "timestamp": 100.0},
        {"metric": "up", "labels": {"machine": "lambda2"}, "value": 1.0, "timestamp": 100.0},
        {"metric": "cpu_seconds", "labels": {"machine": "marconi-01"}, "value": 5.0, "timestamp": 100.0},
    ]
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        for rec in metric_lines:
            f.write(json.dumps(rec) + "\n")
        metrics_path = Path(f.name)

    assert read_eval_metrics(path=metrics_path)[1] == 3
    assert read_eval_metrics(metric="cpu", path=metrics_path)[1] == 1
    assert read_eval_metrics(machine="marconi-01", path=metrics_path)[1] == 2
    capped, total = read_eval_metrics(machine="marconi-01", limit=1, path=metrics_path)
    assert (len(capped), total) == (1, 2)
    metrics_path.unlink()

    log_lines = [
        {"machine": "marconi-01", "timestamp_ns": 1, "labels": {"detected_level": "info"}, "line": "starting up"},
        {"machine": "marconi-01", "timestamp_ns": 2, "labels": {"detected_level": "error"}, "line": "ERROR: disk full"},
        {"machine": "lambda2", "timestamp_ns": 3, "labels": {"detected_level": "error"}, "line": "ERROR: OOM killed"},
    ]
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        for rec in log_lines:
            f.write(json.dumps(rec) + "\n")
        logs_path = Path(f.name)

    assert read_eval_logs(path=logs_path)[1] == 3
    assert read_eval_logs(contains="ERROR", path=logs_path)[1] == 2
    assert read_eval_logs(contains="ERROR", machine="lambda2", path=logs_path)[1] == 1
    assert read_eval_logs(level="error", path=logs_path)[1] == 2
    assert [r["timestamp_ns"] for r in read_eval_logs(path=logs_path)[0]] == [3, 2, 1]
    newest, total = read_eval_logs(limit=1, path=logs_path)
    assert ([r["timestamp_ns"] for r in newest], total) == ([3], 3)
    logs_path.unlink()

    print("selftest ok")


if __name__ == "__main__":
    _selftest()
