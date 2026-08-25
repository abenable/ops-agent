#!/usr/bin/env python3
"""Stream-filter a promtool tsdb dump-openmetrics dump: stdin in, stdout out. Tags every series with a machine="<name>" label and keeps only the first sample per series per --step-seconds bucket. Relies on each series' own samples appearing in non-decreasing timestamp order within one dump (true for a single promtool run), so per-series bucket memory is enough -- the whole file never has to be buffered."""

import argparse
import re
import sys
from collections.abc import Iterable, Iterator

LINE_RE = re.compile(r"^([A-Za-z_:][A-Za-z0-9_:]*)(\{[^}]*\})?\s+(\S+)\s+(\S+)\s*$")


def downsample(lines: Iterable[str], machine: str, step_seconds: int) -> Iterator[str]:
    last_bucket: dict[str, int] = {}
    for line in lines:
        line = line.rstrip("\n")
        if not line or line.startswith("#"):
            continue
        m = LINE_RE.match(line)
        if not m:
            continue
        name, labels, value, ts = m.groups()
        series_key = name + (labels or "")
        bucket = int(float(ts)) // step_seconds
        if last_bucket.get(series_key) == bucket:
            continue
        last_bucket[series_key] = bucket
        inner = labels[1:-1] if labels else ""
        new_labels = f'machine="{machine}",{inner}' if inner else f'machine="{machine}"'
        yield f"{name}{{{new_labels}}} {value} {ts}"


def _selftest() -> None:
    lines = [
        "# EOF",
        'up{job="a"} 1 100.0',
        'up{job="a"} 1 101.0',
        'up{job="a"} 1 161.0',
        "no_labels_metric 5 100.0",
    ]
    out = list(downsample(lines, "marconi-01", step_seconds=60))
    assert out == [
        'up{machine="marconi-01",job="a"} 1 100.0',
        'up{machine="marconi-01",job="a"} 1 161.0',
        'no_labels_metric{machine="marconi-01"} 5 100.0',
    ], out
    print("selftest ok")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--machine")
    parser.add_argument("--step-seconds", type=int, default=300)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()

    if args.selftest:
        _selftest()
        return

    if not args.machine:
        parser.error("--machine is required")

    kept = 0
    for out_line in downsample(sys.stdin, args.machine, args.step_seconds):
        sys.stdout.write(out_line + "\n")
        kept += 1
    print(f"[{args.machine}] kept={kept}", file=sys.stderr)


if __name__ == "__main__":
    main()
