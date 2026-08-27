"""Aggregate eval transcripts per model into comparison tables.

Usage: analyze.py <model_tag> [<model_tag> ...]
Reads eval/logs/<model_tag>/*.json.
"""
import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

LOGS = Path("/home/marconi/agent/eval/logs")


def load_runs(tag: str) -> list[dict]:
    runs = []
    for path in sorted(glob.glob(str(LOGS / tag / "*.json"))):
        d = json.loads(Path(path).read_text())
        # keep only the latest transcript per label
        runs = [r for r in runs if r["label"] != d["label"]]
        runs.append(d)
    return sorted(runs, key=lambda r: r["label"])


def call_stats(d: dict) -> tuple[int, int, list[str], dict[str, int]]:
    """-> (valid, invalid, invalid_names, per-tool invocation counts)

    Transcripts don't carry tool_call ids, so pair each tool message with the
    oldest still-pending call in order (calls and results are sequential).
    """
    pending: list[str] = []
    valid, invalid, invalid_names = 0, 0, []
    per_tool = defaultdict(int)
    for c in d["calls"]:
        r = c["response"]
        if r["role"] == "ai":
            for tc in r.get("tool_calls") or []:
                pending.append(tc["name"])
                per_tool[tc["name"]] += 1
        elif r["role"] == "tool" and pending:
            name = pending.pop(0)
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

    # per-notebook comparison
    labels = sorted({r["label"] for a in per_model.values() for r in a["runs"]})
    print("== PER-CASE COMPARISON ==")
    print(f"{'case':<44}" + "".join(f"{t[:26]:>28}" for t in tags))
    for label in labels:
        cells = []
        for tag in tags:
            run = next((r for r in per_model[tag]["runs"] if r["label"] == label), None)
            if not run:
                cells.append(f"{'-':>28}")
                continue
            valid, invalid, inv_names, _ = call_stats(run)
            u = run["total_usage"]
            flag = f" [{','.join(sorted(set(inv_names)))}]" if inv_names else ""
            cells.append(f"{valid}v/{invalid}i {u['total_tokens']:>5}t {run['duration_ms']:>6}ms{flag:>0}")
        print(f"{label:<44}" + "".join(f"{c:>28}" for c in cells))

    print("\n== MODEL AVERAGES ==")
    for tag, a in per_model.items():
        n = max(a["n"], 1)
        print(
            f"{tag:<18} runs={a['n']:>2}  valid_calls/run={a['valid']/n:.2f}  "
            f"invalid_calls/run={a['invalid']/n:.2f}  runs_with_hallucination={a['hallu_runs']}/{a['n']}  "
            f"tokens/run={a['tokens']/n:.0f}  ms/run={a['ms']/n:.0f}"
        )

    print("\n== TOKENS PER TOOL (avg tokens per invocation | total) ==")
    for tag, a in per_model.items():
        rows = sorted(a["per_tool"].items(), key=lambda kv: -kv[1][1])
        print(f"-- {tag}")
        for name, (cnt, toks) in rows:
            print(f"   {name:<28} n={cnt:<3} avg={toks/cnt:>7.0f}  total={toks:>8.0f}")


main()
