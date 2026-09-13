"""Aggregate eval transcripts per model into comparison tables.

Usage: analyze.py <model_tag> [<model_tag> ...]
Reads eval/logs/<model_tag>/*.json. Every transcript counts: repeated runs of
the same case are averaged, not discarded, because a single run of a
non-deterministic model is an anecdote.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

LOGS = Path(__file__).resolve().parent / "logs"


def load_runs(tag: str) -> list[dict]:
    runs = [json.loads(p.read_text()) for p in sorted((LOGS / tag).glob("*.json"))]
    return sorted(runs, key=lambda r: (r["label"], r.get("thread_id", "")))


def call_stats(d: dict) -> tuple[int, int, list[str], dict[str, int]]:
    """-> (valid, invalid, invalid_names, per-tool invocation counts)

    Transcripts carry the tool_call id on both sides, so match each result to
    the call that produced it; parallel calls would defeat positional pairing.
    """
    by_id: dict[str, str] = {}
    valid, invalid, invalid_names = 0, 0, []
    per_tool = defaultdict(int)
    for c in d["calls"]:
        r = c["response"]
        if r["role"] == "ai":
            for tc in r.get("tool_calls") or []:
                by_id[tc.get("id")] = tc["name"]
                per_tool[tc["name"]] += 1
        elif r["role"] == "tool":
            name = by_id.pop(r.get("tool_call_id"), "?")
            if "is not a valid tool" in r.get("content", ""):
                invalid += 1
                invalid_names.append(name)
            else:
                valid += 1
    return valid, invalid, invalid_names, dict(per_tool)


def tool_token_costs(d: dict) -> dict[str, list[int]]:
    """Attribute tokens to tools: the calling AI turn's total + the next turn's input."""
    costs = defaultdict(list)
    calls = d["calls"]
    ai_idx = [i for i, c in enumerate(calls) if c["response"]["role"] == "ai" and c["usage"]]
    for pos, i in enumerate(ai_idx):
        tcs = calls[i]["response"].get("tool_calls") or []
        if not tcs:
            continue
        turn_total = calls[i]["usage"]["total_tokens"]
        nxt = calls[ai_idx[pos + 1]]["usage"]["input_tokens"] if pos + 1 < len(ai_idx) else 0
        share_call, share_next = turn_total / len(tcs), nxt / len(tcs)
        for tc in tcs:
            costs[tc["name"]].append(share_call + share_next)
    return costs


def main() -> None:
    tags = sys.argv[1:]
    per_model = {}
    for tag in tags:
        runs = load_runs(tag)
        agg = {
            "runs": runs, "n": len(runs),
            "valid": 0, "invalid": 0, "tokens": 0, "ms": 0,
            "hallu_runs": 0, "per_tool": defaultdict(lambda: [0, 0.0]),  # count, tokens
        }
        for d in runs:
            valid, invalid, inv_names, _ = call_stats(d)
            agg["valid"] += valid
            agg["invalid"] += invalid
            agg["tokens"] += d["total_usage"]["total_tokens"]
            agg["ms"] += d["duration_ms"]
            if invalid:
                agg["hallu_runs"] += 1
            for name, costs in tool_token_costs(d).items():
                agg["per_tool"][name][0] += len(costs)
                agg["per_tool"][name][1] += sum(costs)
        per_model[tag] = agg

    labels = sorted({r["label"] for a in per_model.values() for r in a["runs"]})
    print("== PER-CASE COMPARISON (mean over n runs) ==")
    print(f"{'case':<40}" + "".join(f"{t[:30]:>32}" for t in tags))
    for label in labels:
        cells = []
        for tag in tags:
            runs = [r for r in per_model[tag]["runs"] if r["label"] == label]
            if not runs:
                cells.append("-")
                continue
            stats = [call_stats(r) for r in runs]
            n = len(runs)
            valid = sum(s[0] for s in stats) / n
            invalid = sum(s[1] for s in stats) / n
            inv_names = {name for s in stats for name in s[2]}
            toks = sum(r["total_usage"]["total_tokens"] for r in runs) / n
            ms = sum(r["duration_ms"] for r in runs) / n
            errs = sum(1 for r in runs if r.get("error"))
            flag = f" [{','.join(sorted(inv_names))}]" if inv_names else ""
            flag += f" ERR{errs}" if errs else ""
            cells.append(f"n={n} {valid:.1f}v/{invalid:.1f}i {toks:>6.0f}t {ms:>6.0f}ms{flag}")
        print(f"{label:<40}" + "".join(f"{c:>32}" for c in cells))

    print("\n== MODEL AVERAGES ==")
    for tag, a in per_model.items():
        n = max(a["n"], 1)
        print(
            f"{tag:<18} runs={a['n']:>2}  valid_calls/run={a['valid']/n:.2f}  "
            f"invalid_calls/run={a['invalid']/n:.2f}  runs_with_hallucination={a['hallu_runs']}/{a['n']}  "
            f"errored_runs={sum(1 for r in a['runs'] if r.get('error'))}/{a['n']}  "
            f"tokens/run={a['tokens']/n:.0f}  ms/run={a['ms']/n:.0f}"
        )

    print("\n== TOKENS PER TOOL (avg tokens per invocation | total) ==")
    for tag, a in per_model.items():
        rows = sorted(a["per_tool"].items(), key=lambda kv: -kv[1][1])
        print(f"-- {tag}")
        for name, (cnt, toks) in rows:
            print(f"   {name:<28} n={cnt:<3} avg={toks/cnt:>7.0f}  total={toks:>8.0f}")


main()
