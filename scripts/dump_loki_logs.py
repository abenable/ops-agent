#!/usr/bin/env python3
"""Page through a Loki query_range and dump every log line as JSONL, tagged with --machine. Writes to stdout; one JSON object per line."""

import argparse
import json
import sys
import urllib.parse
import urllib.request


def query_page(base_url: str, query: str, start_ns: int, end_ns: int, limit: int) -> dict:
    params = {
        "query": query,
        "start": str(start_ns),
        "end": str(end_ns),
        "limit": str(limit),
        "direction": "forward",
    }
    url = f"{base_url}/loki/api/v1/query_range?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as r:  # noqa: S310
        return json.load(r)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--machine", required=True)
    ap.add_argument("--query", default='{job="docker-logs"}')
    ap.add_argument("--start-ns", type=int, required=True)
    ap.add_argument("--end-ns", type=int, required=True)
    ap.add_argument("--limit", type=int, default=5000)
    args = ap.parse_args()

    start = args.start_ns
    total = 0
    while start <= args.end_ns:
        data = query_page(args.base_url, args.query, start, args.end_ns, args.limit)
        streams = data.get("data", {}).get("result", [])
        page_entries = 0
        max_ts = start
        for stream in streams:
            labels = stream["stream"]
            for ts_str, line in stream["values"]:
                ts = int(ts_str)
                max_ts = max(max_ts, ts)
                rec = {"machine": args.machine, "timestamp_ns": ts, "labels": labels, "line": line}
                sys.stdout.write(json.dumps(rec) + "\n")
                page_entries += 1
        total += page_entries
        print(f"[{args.machine}] page entries={page_entries} total={total}", file=sys.stderr)
        if page_entries < args.limit:
            break
        start = max_ts + 1

    print(f"[{args.machine}] done total={total}", file=sys.stderr)


if __name__ == "__main__":
    main()
