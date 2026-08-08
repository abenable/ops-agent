"""Plot eval results from trials.jsonl: performance, cost, efficiency.

Reads the line-delimited JSON trials log written by ``python -m agent eval``
and produces comparison figures across model labels (one figure per metric),
saved as PNG into <out-dir>/plots/.

Usage::

    python scripts/plot_evals.py eval_runs/trials.jsonl
    python scripts/plot_evals.py eval_runs/trials.jsonl --price scripts/prices.json
    python scripts/plot_evals.py eval_runs/trials.jsonl --out-dir eval_runs/plots

The price file maps a model name to USD per 1M tokens::

    {"gpt-4o-mini": {"in": 0.15, "out": 0.60},
     "claude-3-5-haiku": {"in": 0.80, "out": 4.00}}

Self-hosted vLLM models (not in the price file) cost $0; for those, use the
tokens/sec and pass-rate-per-1M-tokens figures for efficiency instead of cost.
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: save to files, no display needed
import matplotlib.pyplot as plt


def load_trials(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def group_by_label(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        grouped[r.get("label") or r.get("model") or "unknown"].append(r)
    return grouped


def _mean(rows: list[dict], key: str) -> float:
    vals = [float(r.get(key) or 0.0) for r in rows]
    return statistics.mean(vals) if vals else 0.0


def _pass_rate(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    return sum(1 for r in rows if r.get("passed")) / len(rows)


def _cost(rows: list[dict], prices: dict) -> float:
    """USD for a set of trials, from per-1M-token prices for the model."""
    if not rows:
        return 0.0
    model = rows[0].get("model") or rows[0].get("label")
    p = prices.get(model, {})
    pin, pout = float(p.get("in", 0.0)), float(p.get("out", 0.0))
    return (
        sum(float(r.get("prompt_tokens") or 0) for r in rows) * pin / 1e6
        + sum(float(r.get("completion_tokens") or 0) for r in rows) * pout / 1e6
    )


def _bar(ax, labels, values, title, ylabel, color="#4C72B0"):
    bars = ax.bar(labels, values, color=color)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.tick_params(axis="x", rotation=20)
    for b, v in zip(bars, values):
        ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.1f}",
                ha="center", va="bottom", fontsize=8)
    ax.set_ylim(0, max(values) * 1.15 if values else 1)


def _scatter(ax, xs, ys, labels, title, xlabel, ylabel):
    ax.scatter(xs, ys, s=90)
    for x, y, lab in zip(xs, ys, labels):
        ax.annotate(lab, (x, y), textcoords="offset points", xytext=(6, 6), fontsize=8)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.3)


def plot_all(rows: list[dict], prices: dict, out_dir: Path) -> list[Path]:
    grouped = group_by_label(rows)
    labels = sorted(grouped)
    if not labels:
        print("no trials found")
        return []
    out_dir.mkdir(parents=True, exist_ok=True)

    pass_rates = [_pass_rate(grouped[l]) for l in labels]
    mean_tokens = [_mean(grouped[l], "total_tokens") for l in labels]
    mean_dur = [_mean(grouped[l], "duration_s") for l in labels]
    mean_ttft = [_mean(grouped[l], "time_to_first_token_s") for l in labels]
    mean_tps = [_mean(grouped[l], "tokens_per_sec") for l in labels]
    mean_turns = [_mean(grouped[l], "n_turns") for l in labels]
    mean_tools = [_mean(grouped[l], "n_tool_calls") for l in labels]
    costs = [_cost(grouped[l], prices) for l in labels]

    saved = []

    def _save(fig, name):
        p = out_dir / name
        fig.tight_layout()
        fig.savefig(p, dpi=130)
        plt.close(fig)
        saved.append(p)
        print(f"wrote {p}")

    # 1. Pass rate by label
    fig, ax = plt.subplots(figsize=(8, 5))
    _bar(ax, labels, pass_rates, "Pass rate by model", "pass rate", "#55A868")
    ax.set_ylim(0, 1.05)
    _save(fig, "pass_rate.png")

    # 2. Mean total tokens by label
    fig, ax = plt.subplots(figsize=(8, 5))
    _bar(ax, labels, mean_tokens, "Mean total tokens per trial", "tokens")
    _save(fig, "total_tokens.png")

    # 3. Mean end-to-end latency by label
    fig, ax = plt.subplots(figsize=(8, 5))
    _bar(ax, labels, mean_dur, "Mean latency per trial", "seconds", "#C44E52")
    _save(fig, "latency.png")

    # 4. Mean time-to-first-token by label
    fig, ax = plt.subplots(figsize=(8, 5))
    _bar(ax, labels, mean_ttft, "Mean time-to-first-token", "seconds", "#8172B2")
    _save(fig, "time_to_first_token.png")

    # 5. Throughput (tokens/sec) by label
    fig, ax = plt.subplots(figsize=(8, 5))
    _bar(ax, labels, mean_tps, "Mean throughput", "tokens/sec", "#937860")
    _save(fig, "tokens_per_sec.png")

    # 6. Efficiency: pass rate vs tokens (lower-left is better: cheap & correct)
    fig, ax = plt.subplots(figsize=(8, 6))
    _scatter(ax, mean_tokens, pass_rates, labels,
             "Efficiency: pass rate vs tokens", "mean total tokens / trial", "pass rate")
    _save(fig, "efficiency_tokens.png")

    # 7. Efficiency: pass rate vs latency
    fig, ax = plt.subplots(figsize=(8, 6))
    _scatter(ax, mean_dur, pass_rates, labels,
             "Efficiency: pass rate vs latency", "mean latency (s)", "pass rate")
    _save(fig, "efficiency_latency.png")

    # 8. Tool-call / turn economy (more = more work to decide)
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    _bar(axes[0], labels, mean_turns, "Mean turns", "turns", "#4C72B0")
    _bar(axes[1], labels, mean_tools, "Mean tool calls", "calls", "#55A868")
    _save(fig, "economy.png")

    # 9. Cost vs pass rate (only if any label has nonzero cost)
    if any(c > 0 for c in costs):
        fig, ax = plt.subplots(figsize=(8, 6))
        _scatter(ax, costs, pass_rates, labels,
                 "Cost efficiency: pass rate vs cost", "cost (USD)", "pass rate")
        _save(fig, "cost_vs_pass.png")
        # per-trial cost bar
        per_trial = [c / max(len(grouped[l]), 1) for l, c in zip(labels, costs)]
        fig, ax = plt.subplots(figsize=(8, 5))
        _bar(ax, labels, per_trial, "Mean cost per trial", "USD", "#CCB974")
        _save(fig, "cost_per_trial.png")

    # Summary table (stdout) for the report
    print("\n=== summary ===")
    hdr = f"{'label':28s} {'pass':>6s} {'tokens':>8s} {'lat_s':>7s} {'ttft_s':>7s} {'tok/s':>7s} {'turns':>6s} {'cost$':>7s}"
    print(hdr)
    for i, l in enumerate(labels):
        print(f"{l:28s} {pass_rates[i]:>6.0%} {mean_tokens[i]:>8.0f} "
              f"{mean_dur[i]:>7.1f} {mean_ttft[i]:>7.1f} {mean_tps[i]:>7.1f} "
              f"{mean_turns[i]:>6.1f} {costs[i]:>7.2f}")

    # Per-task breakdown for each label (informative with a single model too).
    for l in labels:
        _per_task(grouped[l], out_dir, l)
    return saved


def _per_task(rows: list[dict], out_dir: Path, label: str):
    """Pass rate + mean tokens per task for one label (horizontal bars)."""
    by_task: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_task[r.get("task", "?")].append(r)
    tasks = sorted(by_task)
    pr = [sum(1 for r in by_task[t] if r.get("passed")) / len(by_task[t]) for t in tasks]
    tok = [statistics.mean(float(r.get("total_tokens") or 0) for r in by_task[t]) for t in tasks]

    fig, axes = plt.subplots(1, 2, figsize=(13, max(5, 0.35 * len(tasks))))
    axes[0].barh(tasks, pr, color="#55A868")
    axes[0].set_xlim(0, 1.05)
    axes[0].set_xlabel("pass rate")
    axes[0].set_title(f"{label}: pass rate per task")
    axes[1].barh(tasks, tok, color="#4C72B0")
    axes[1].set_xlabel("mean total tokens")
    axes[1].set_title(f"{label}: tokens per task")
    fig.tight_layout()
    safe = label.replace("/", "_").replace(":", "_").replace(" ", "_")
    p = out_dir / f"per_task_{safe}.png"
    fig.savefig(p, dpi=130)
    plt.close(fig)
    print(f"wrote {p}")


def main():
    ap = argparse.ArgumentParser(description="Plot eval comparison figures.")
    ap.add_argument("trials", type=Path, help="path to trials.jsonl")
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="where to save PNGs (default: <trials dir>/plots)")
    ap.add_argument("--price", type=Path, default=None,
                    help="JSON file mapping model name -> {in, out} USD per 1M tokens")
    args = ap.parse_args()

    rows = load_trials(args.trials)
    prices = {}
    if args.price:
        prices = json.loads(args.price.read_text(encoding="utf-8"))
    out = args.out_dir or args.trials.parent / "plots"
    files = plot_all(rows, prices, out)
    print(f"\n{len(files)} figures saved to {out}/")


if __name__ == "__main__":
    main()
