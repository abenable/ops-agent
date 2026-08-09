"""Aggregate eval trials into chart-ready metric tables + dashboard PNGs.

Reads the line-delimited ``trials.jsonl`` written by ``python -m agent eval`` and
emits:
  - ``metrics.json``  — every metric grouped by (model, task) and (model, suite)
  - 4 dashboard PNGs in <out-dir>/:
      1. accuracy_vs_cost.png   — success_rate vs cost_per_success (model choice)
      2. efficiency_over_tasks  — tokens / latency grouped bars with std bars
      3. path_efficiency.png    — path_ratio box plot per model
      4. safety_heatmap.png      — Suite 3 pass/fail, never averaged
  - a stdout headline summary table

Run recipe (per model, then aggregate)::

    python -m agent eval --judge --trials 5 --label qwen2.5-7b
    python scripts/aggregate_evals.py src/agent/eval/runs/trials.jsonl --price scripts/prices.json

Self-hosted models cost $0 (compare on tokens/sec + pass-rate-per-1M-tokens);
hosted A/B needs real USD-per-1M-token rates in the price file.
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt


# --- loading / grouping -----------------------------------------------------

def load_trials(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def group(rows: list[dict], *keys) -> dict[tuple, list[dict]]:
    out: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        out[tuple(r.get(k) for k in keys)].append(r)
    return out


# --- stats helpers ----------------------------------------------------------

def _vals(rows: list[dict], key: str) -> list[float]:
    return [float(r.get(key) or 0.0) for r in rows]


def mean(rows: list[dict], key: str) -> float:
    v = _vals(rows, key)
    return statistics.mean(v) if v else 0.0


def _pct(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    # linear interpolation between closest ranks
    k = (len(sorted_vals) - 1) * p / 100.0
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def p95(rows: list[dict], key: str) -> float:
    return _pct(sorted(_vals(rows, key)), 95)


def std(rows: list[dict], key: str) -> float:
    v = _vals(rows, key)
    return statistics.pstdev(v) if len(v) > 1 else 0.0


def cov(rows: list[dict], key: str) -> float:
    m = mean(rows, key)
    return std(rows, key) / m if m else 0.0


def pass_rate(rows: list[dict]) -> float:
    return sum(1 for r in rows if r.get("passed")) / len(rows) if rows else 0.0


def cost(rows: list[dict], prices: dict) -> float:
    if not rows:
        return 0.0
    model = rows[0].get("model") or rows[0].get("label")
    p = prices.get(model, {})
    pin = float(p.get("in", 0.0))
    pout = float(p.get("out", 0.0))
    pcache = float(p.get("cache_read", 0.0))
    return (
        sum(float(r.get("prompt_tokens") or 0) for r in rows) * pin / 1e6
        + sum(float(r.get("completion_tokens") or 0) for r in rows) * pout / 1e6
        + sum(float(r.get("cache_read_tokens") or 0) for r in rows) * pcache / 1e6
    )


def cost_per_success(rows: list[dict], prices: dict) -> float:
    wins = sum(1 for r in rows if r.get("passed"))
    if not wins:
        return float("inf")
    return cost(rows, prices) / wins


def path_ratio(rows: list[dict]) -> list[float]:
    """per-trial actual / reference tool-call count (1.0 = optimal)."""
    out = []
    for r in rows:
        ref = int(r.get("reference_n_tool_calls") or 0)
        if ref > 0:
            out.append(max(0.0, float(r.get("n_tool_calls") or 0) / ref))
    return out


def redundant_rate(rows: list[dict]) -> float:
    tot = sum(int(r.get("n_tool_calls") or 0) for r in rows)
    if not tot:
        return 0.0
    return sum(int(r.get("redundant_calls") or 0) for r in rows) / tot


def wrong_branch_rate(rows: list[dict]) -> float:
    tot = sum(int(r.get("n_tool_calls") or 0) for r in rows)
    if not tot:
        return 0.0
    return sum(int(r.get("off_path_calls") or 0) for r in rows) / tot


# --- the metric table -------------------------------------------------------

def metrics_for(rows: list[dict], prices: dict) -> dict:
    pr = path_ratio(rows)
    return {
        "n_trials": len(rows),
        "success_rate": pass_rate(rows),
        "step_accuracy": mean(rows, "score"),
        "tokens_mean": mean(rows, "total_tokens"),
        "tokens_p95": p95(rows, "total_tokens"),
        "input_tokens_mean": mean(rows, "prompt_tokens"),
        "output_tokens_mean": mean(rows, "completion_tokens"),
        "cache_read_tokens_mean": mean(rows, "cache_read_tokens"),
        "latency_mean_s": mean(rows, "duration_s"),
        "latency_p95_s": p95(rows, "duration_s"),
        "llm_time_mean_s": mean(rows, "llm_time_s"),
        "tool_time_mean_s": mean(rows, "tool_time_s"),
        "overhead_time_mean_s": mean(rows, "overhead_time_s"),
        "latency_std_s": std(rows, "duration_s"),
        "latency_cov": cov(rows, "duration_s"),
        "cost": cost(rows, prices),
        "cost_per_success": cost_per_success(rows, prices),
        "cost_per_trial": cost(rows, prices) / len(rows) if rows else 0.0,
        "path_ratio_mean": statistics.mean(pr) if pr else 0.0,
        "path_ratio_std": statistics.pstdev(pr) if len(pr) > 1 else 0.0,
        "redundant_rate": redundant_rate(rows),
        "wrong_branch_rate": wrong_branch_rate(rows),
        "tokens_per_sec": mean(rows, "tokens_per_sec"),
        "safety_violation_rate": (
            sum(1 for r in rows if r.get("safety_violation")) / len(rows) if rows else 0.0
        ),
    }


def build_metrics(rows: list[dict], prices: dict) -> dict:
    models = sorted({r.get("model") or r.get("label") or "unknown" for r in rows})
    by_model = group(rows, "model")
    by_model_task = group(rows, "model", "task")
    by_model_suite = group(rows, "model", "suite")
    return {
        "models": models,
        "by_model": {m: metrics_for(rs, prices) for (m,), rs in by_model.items()},
        "by_model_task": {
            f"{m}|{t}": metrics_for(rs, prices)
            for (m, t), rs in by_model_task.items()
        },
        "by_model_suite": {
            f"{m}|suite{s}": metrics_for(rs, prices)
            for (m, s), rs in by_model_suite.items()
        },
    }


# --- charts -----------------------------------------------------------------

def _save(fig, name, out_dir: Path) -> Path:
    p = out_dir / name
    fig.tight_layout()
    fig.savefig(p, dpi=130)
    plt.close(fig)
    print(f"wrote {p}")
    return p


def chart_accuracy_vs_cost(mx: dict, out_dir: Path) -> list[Path]:
    """success_rate vs cost_per_success, one point per (model, task)."""
    pts = []
    for key, m in mx["by_model_task"].items():
        model, task = key.split("|", 1)
        cps = m["cost_per_success"]
        if cps == float("inf"):
            continue
        pts.append((model, task, cps, m["success_rate"]))
    if not pts:
        return []
    fig, ax = plt.subplots(figsize=(9, 6))
    colors = {m: f"C{i}" for i, m in enumerate(mx["models"])}
    plotted = set()
    for model, task, cps, sr in pts:
        ax.scatter(cps, sr, s=70, color=colors[model],
                   label=model if model not in plotted else "")
        plotted.add(model)
    ax.legend(loc="lower right", fontsize=8)
    ax.set_xlabel("cost per successful task (USD)")
    ax.set_ylabel("success rate")
    ax.set_title("Accuracy vs cost (bottom-right = best value)")
    ax.grid(True, alpha=0.3)
    return [_save(fig, "accuracy_vs_cost.png", out_dir)]


def chart_efficiency_over_tasks(mx: dict, out_dir: Path) -> list[Path]:
    """Tokens + latency per task, grouped bars per model, ±std error bars."""
    tasks = sorted({k.split("|", 1)[1] for k in mx["by_model_task"]})
    models = mx["models"]
    if not tasks or len(models) < 1:
        return []
    import numpy as np
    x = np.arange(len(tasks))
    w = 0.8 / max(1, len(models))
    saved = []
    for yi, (key, ylabel, title, fname) in enumerate([
        ("tokens_mean", "tokens", "Mean tokens per task", "efficiency_tokens.png"),
        ("latency_mean_s", "seconds", "Mean latency per task", "efficiency_latency.png"),
    ]):
        fig, ax = plt.subplots(figsize=(max(8, 0.5 * len(tasks)), 5))
        for i, model in enumerate(models):
            vals, errs = [], []
            for t in tasks:
                m = mx["by_model_task"].get(f"{model}|{t}", {})
                vals.append(m.get(key, 0.0))
                errs.append(m.get("latency_std_s", 0.0) if key == "latency_mean_s" else 0.0)
            ax.bar(x + i * w, vals, w, yerr=errs, capsize=3, label=model)
        ax.set_xticks(x + w * (len(models) - 1) / 2)
        ax.set_xticklabels(tasks, rotation=30, ha="right", fontsize=8)
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.legend(fontsize=8)
        saved.append(_save(fig, fname, out_dir))
    return saved


def chart_path_efficiency(mx: dict, rows: list[dict], out_dir: Path) -> list[Path]:
    """path_ratio box plot per model (median + spread)."""
    by_model = group(rows, "model")
    data, labels = [], []
    for model in sorted(by_model):
        ratios = path_ratio(by_model[model])
        if ratios:
            data.append(ratios)
            labels.append(model)
    if not data:
        return []
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.boxplot(data, tick_labels=labels, showmeans=True)
    ax.axhline(1.0, color="green", linestyle="--", linewidth=1, label="optimal (1.0)")
    ax.set_ylabel("path_ratio (actual / reference tool calls)")
    ax.set_title("Path efficiency (lower + tighter = better)")
    ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=8)
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3, axis="y")
    return [_save(fig, "path_efficiency.png", out_dir)]


def chart_safety_heatmap(rows: list[dict], out_dir: Path) -> list[Path]:
    """Suite 3 pass/fail per (model, task). Binary, never averaged."""
    safety = [r for r in rows if str(r.get("suite")) == "3"]
    if not safety:
        return []
    by_mt = group(safety, "model", "task")
    models = sorted({m for (m, _t) in by_mt})
    tasks = sorted({t for (_m, t) in by_mt})
    if not models or not tasks:
        return []
    # cell = pass rate (0.0 fail..1.0 pass); n/a if no trials
    grid = [[None] * len(tasks) for _ in models]
    for (m, t), rs in by_mt.items():
        grid[models.index(m)][tasks.index(t)] = pass_rate(rs)
    import numpy as np
    arr = np.array([[0.5 if v is None else v for v in row] for row in grid], dtype=float)
    fig, ax = plt.subplots(figsize=(max(7, 0.6 * len(tasks)), max(3, 0.5 * len(models))))
    im = ax.imshow(arr, aspect="auto", cmap="RdYlGn", vmin=0.0, vmax=1.0)
    ax.set_xticks(range(len(tasks)))
    ax.set_xticklabels(tasks, rotation=30, ha="right", fontsize=8)
    ax.set_yticks(range(len(models)))
    ax.set_yticklabels(models, fontsize=8)
    for i in range(len(models)):
        for j in range(len(tasks)):
            v = grid[i][j]
            txt = "n/a" if v is None else ("PASS" if v == 1.0 else ("FAIL" if v == 0.0 else f"{v:.0%}"))
            ax.text(j, i, txt, ha="center", va="center", fontsize=8,
                    color="white" if v is not None and 0.25 < v < 0.75 else "black")
    ax.set_title("Safety (Suite 3) — pass/fail, never averaged")
    fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    return [_save(fig, "safety_heatmap.png", out_dir)]


def summary_table(mx: dict) -> str:
    lines = ["\n=== headline summary (per model) ==="]
    hdr = f"{'model':24s} {'succ':>6s} {'step':>6s} {'cost/succ':>10s} {'lat_s':>7s} {'p95_s':>7s} {'path':>5s} {'redund':>7s} {'wrong':>6s} {'safety':>7s}"
    lines.append(hdr)
    for m in mx["models"]:
        d = mx["by_model"].get(m, {})
        cps = d.get("cost_per_success", float("inf"))
        cps_s = "inf" if cps == float("inf") else f"{cps:.4f}"
        lines.append(
            f"{m:24s} {d.get('success_rate',0):>6.0%} {d.get('step_accuracy',0):>6.0%} "
            f"{cps_s:>10s} {d.get('latency_mean_s',0):>7.1f} {d.get('latency_p95_s',0):>7.1f} "
            f"{d.get('path_ratio_mean',0):>5.2f} {d.get('redundant_rate',0):>7.0%} "
            f"{d.get('wrong_branch_rate',0):>6.0%} {d.get('safety_violation_rate',0):>7.0%}"
        )
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Aggregate eval trials into metrics + charts.")
    ap.add_argument("trials", type=Path, help="path to trials.jsonl")
    ap.add_argument("--price", type=Path, default=None,
                    help="JSON: model -> {in, out, cache_read} USD per 1M tokens")
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="where to save metrics.json + PNGs (default: <trials dir>/plots)")
    args = ap.parse_args()

    rows = load_trials(args.trials)
    if not rows:
        print("no trials found")
        raise SystemExit(1)
    prices = json.loads(args.price.read_text(encoding="utf-8")) if args.price else {}
    out = args.out_dir or args.trials.parent / "plots"
    out.mkdir(parents=True, exist_ok=True)

    mx = build_metrics(rows, prices)
    (out / "metrics.json").write_text(json.dumps(mx, indent=2, default=str), encoding="utf-8")
    print(f"wrote {out / 'metrics.json'}")

    saved = []
    saved += chart_accuracy_vs_cost(mx, out)
    saved += chart_efficiency_over_tasks(mx, out)
    saved += chart_path_efficiency(mx, rows, out)
    saved += chart_safety_heatmap(rows, out)

    print(summary_table(mx))
    print(f"\n{len(saved)} figures saved to {out}/")


if __name__ == "__main__":
    main()
