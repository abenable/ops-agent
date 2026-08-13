"""Render a two-model eval comparison into print-ready charts for the report.

Reads a ``trials.jsonl`` with a ``model`` field carrying more than one value
(as written by ``python -m agent eval`` runs against different providers) and
the task YAML files under ``agent/eval/tasks/`` (to exclude tasks flagged
``requires_fault_staging`` from the pass-rate comparison — neither model can
fairly pass those in this environment). Emits two PNGs: pass rate by suite
per model, and mean token/latency cost per model. Every number comes from the
trials file; nothing here is estimated.

Usage::

    python scripts/eval_model_comparison_charts.py baselines/model_comparison/trials.jsonl --out-dir docs/pdf/figures
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

SLOT1 = "#2a78d6"  # categorical slot 1 (blue)
SLOT2 = "#eb6834"  # categorical slot 2 (orange)
TEXT = "#0b0b0b"
MUTED = "#52514e"

SUITE_NAMES = {
    "1": "1 · Status & basics",
    "2": "2 · Root cause",
    "3": "3 · Safety",
    "4": "4 · Resilience",
    "5": "5 · Reporting",
}
SUITE_ORDER = ["1", "2", "3", "4", "5"]

plt.rcParams.update({
    "font.size": 11,
    "axes.edgecolor": "#d0cfc8",
    "axes.labelcolor": TEXT,
    "text.color": TEXT,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "axes.titleweight": "bold",
})


def _clean_axes(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.grid(axis="x", color="#e6e5df", linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)


def _flagged_unstaged_tasks(tasks_dir: Path) -> set[str]:
    import yaml

    out = set()
    for p in sorted(tasks_dir.glob("*.yml")):
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if data.get("requires_fault_staging"):
            out.add(p.stem)
    return out


def load(trials_path: Path) -> list[dict]:
    return [json.loads(l) for l in trials_path.read_text(encoding="utf-8").splitlines() if l.strip()]


def chart_pass_rate_by_suite(rows: list[dict], unstaged: set[str], models: list[str], out_dir: Path) -> Path:
    fair = [r for r in rows if r["task"] not in unstaged]
    by_ms = defaultdict(list)
    for r in fair:
        by_ms[(r["model"], str(r["suite"]))].append(r)

    suites = [s for s in SUITE_ORDER if any((m, s) in by_ms for m in models)]
    fig, ax = plt.subplots(figsize=(9.5, 5.5))
    y = np.arange(len(suites))
    h = 0.35
    colors = {models[0]: SLOT1, models[1]: SLOT2}

    for i, m in enumerate(models):
        vals, ns = [], []
        for s in suites:
            rs = by_ms.get((m, s), [])
            n = len(rs)
            p = sum(1 for r in rs if r["passed"])
            vals.append((p / n * 100) if n else 0)
            ns.append((p, n))
        offset = (i - 0.5) * h
        bars = ax.barh(y + offset, vals, height=h, color=colors[m], label=m, zorder=3)
        for yi, (v, (p, n)) in zip(y + offset, zip(vals, ns)):
            if n:
                ax.text(v + 1.5, yi, f"{p}/{n}", va="center", fontsize=9, color=TEXT)

    ax.set_yticks(list(y))
    ax.set_yticklabels([SUITE_NAMES[s] for s in suites])
    ax.invert_yaxis()
    ax.set_xlim(0, 112)
    ax.set_xlabel("pass rate on fairly-gradeable tasks (%)")
    _clean_axes(ax)
    ax.set_title("Pass rate by suite, fairly-gradeable tasks only")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=2, frameon=False, fontsize=9)
    fig.tight_layout()
    path = out_dir / "model_comparison_pass_rate.png"
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def chart_cost(rows: list[dict], models: list[str], out_dir: Path) -> Path:
    by_model = defaultdict(list)
    for r in rows:
        by_model[r["model"]].append(r)

    colors = {models[0]: SLOT1, models[1]: SLOT2}
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4))
    y = np.arange(len(models))
    for ax, key, xlabel, fmt in (
        (ax1, "duration_s", "mean seconds per investigation", "{:.1f}s"),
        (ax2, "total_tokens", "mean tokens per investigation", "{:.0f}"),
    ):
        vals = [sum(float(r.get(key) or 0) for r in by_model[m]) / len(by_model[m]) for m in models]
        bars = ax.barh(y, vals, height=0.5, color=[colors[m] for m in models], zorder=3)
        ax.set_yticks(list(y))
        ax.set_yticklabels(models)
        ax.invert_yaxis()
        ax.set_xlabel(xlabel)
        for yi, v in zip(y, vals):
            ax.text(v + max(vals) * 0.02, yi, fmt.format(v), va="center", fontsize=10, color=TEXT)
        _clean_axes(ax)
    ax1.set_title("Mean latency per investigation (all trials)")
    ax2.set_title("Mean tokens per investigation (all trials)")
    fig.tight_layout()
    path = out_dir / "model_comparison_cost.png"
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("trials", type=Path, help="path to a trials.jsonl file with a `model` column")
    ap.add_argument("--tasks-dir", type=Path,
                     default=Path(__file__).resolve().parent.parent / "src/agent/eval/tasks")
    ap.add_argument("--out-dir", type=Path, default=Path("docs/pdf/figures"))
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    rows = load(args.trials)
    unstaged = _flagged_unstaged_tasks(args.tasks_dir)
    models = sorted({r["model"] for r in rows})
    if len(models) != 2:
        raise SystemExit(f"expected exactly 2 models in the trials file, found: {models}")

    p1 = chart_pass_rate_by_suite(rows, unstaged, models, args.out_dir)
    print(f"wrote {p1}")
    p2 = chart_cost(rows, models, args.out_dir)
    print(f"wrote {p2}")


if __name__ == "__main__":
    main()
