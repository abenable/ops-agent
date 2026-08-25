#!/usr/bin/env python3
"""Stream-convert combined_metrics.prom (OpenMetrics text) to JSONL. One JSON object per sample: {"metric": str, "labels": {...}, "value": float, "timestamp": float}. stdin in, stdout out -- doesn't hold the file in memory."""

import json
import re
import sys
from collections.abc import Iterable, Iterator

LINE_RE = re.compile(r"^([A-Za-z_:][A-Za-z0-9_:]*)(\{[^}]*\})?\s+(\S+)\s+(\S+)\s*$")
LABEL_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)="((?:[^"\\]|\\.)*)"')


def to_number(s: str) -> float | str:
    try:
        return float(s)
    except ValueError:
        return s


def convert(lines: Iterable[str]) -> Iterator[dict]:
    for line in lines:
        line = line.rstrip("\n")
        if not line or line.startswith("#"):
            continue
        m = LINE_RE.match(line)
        if not m:
            continue
        name, labels, value, ts = m.groups()
        label_dict = dict(LABEL_RE.findall(labels)) if labels else {}
        yield {"metric": name, "labels": label_dict, "value": to_number(value), "timestamp": to_number(ts)}


def _selftest() -> None:
    lines = [
        "# EOF",
        'up{machine="marconi-01",job="a"} 1 100.0',
        "no_labels_metric 5 100.0",
    ]
    out = list(convert(lines))
    assert out == [
        {"metric": "up", "labels": {"machine": "marconi-01", "job": "a"}, "value": 1.0, "timestamp": 100.0},
        {"metric": "no_labels_metric", "labels": {}, "value": 5.0, "timestamp": 100.0},
    ], out
    print("selftest ok")


def main() -> None:
    if "--selftest" in sys.argv:
        _selftest()
        return
    kept = 0
    for rec in convert(sys.stdin):
        sys.stdout.write(json.dumps(rec) + "\n")
        kept += 1
    print(f"kept={kept}", file=sys.stderr)


if __name__ == "__main__":
    main()
