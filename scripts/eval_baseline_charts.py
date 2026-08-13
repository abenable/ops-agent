"""Render baseline eval results into print-ready charts for the technical report.

Reads a ``trials.jsonl`` (as written by ``python -m agent eval``) and the task
YAML files under ``agent/eval/tasks/`` (to know which tasks are flagged
``requires_fault_staging`` — see docs/evals for what that means), then emits
three PNGs: pass/fail by suite, which graders catch the failures, and mean
investigation duration/token usage by suite. Every number comes straight from
the trials file; nothing here is estimated or invented.

Usage::

    python scripts/eval_baseline_charts.py baselines/<run>/trials.jsonl --out-dir docs/pdf/figures
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

GOOD = "#0ca30c"
CRITICAL = "#d03b3b"
GAP = "#9c9c94"
BLUE = "#2a78d6"
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


def _clean_axes(ax, *, x=False, y=True):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    if y:
        ax.spines["left"].set_visible(False)
    if x:
        ax.spines["bottom"].set_visible(False)
    ax.grid(axis="y" if y else "x", color="#e6e5df", linewidth=0.8, zorder=0)
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


def chart_suite_results(rows: list[dict], unstaged: set[str], out_dir: Path) -> Path:
    by_suite = defaultdict(lambda: {"pass": 0, "fail_genuine": 0, "fail_gap": 0})
    for r in rows:
        s = str(r["suite"])
        if r["passed"]:
            by_suite[s]["pass"] += 1
        elif r["task"] in unstaged:
            by_suite[s]["fail_gap"] += 1
        else:
            by_suite[s]["fail_genuine"] += 1

    suites = [s for s in SUITE_ORDER if s in by_suite]
    passed = [by_suite[s]["pass"] for s in suites]
    genuine = [by_suite[s]["fail_genuine"] for s in suites]
    gap = [by_suite[s]["fail_gap"] for s in suites]
    totals = [p + g + u for p, g, u in zip(passed, genuine, gap)]

    fig, ax = plt.subplots(figsize=(9, 5))
    y = range(len(suites))
    ax.barh(y, passed, color=GOOD, height=0.6, label="Passed", zorder=3)
    ax.barh(y, genuine, left=passed, color=CRITICAL, height=0.6, label="Failed", zorder=3)
    left2 = [p + g for p, g in zip(passed, genuine)]
    ax.barh(y, gap, left=left2, color=GAP, height=0.6,
            label="Not fairly gradeable (fault not staged)", zorder=3)

    for i, (p, g, u, t) in enumerate(zip(passed, genuine, gap, totals)):
        x = 0
        for val, txt_color in ((p, "white"), (g, "white"), (u, "white")):
            if val:
                ax.text(x + val / 2, i, str(val), ha="center", va="center",
                         color=txt_color, fontsize=10, fontweight="bold", zorder=4)
            x += val

    ax.set_yticks(list(y))
    ax.set_yticklabels([SUITE_NAMES[s] for s in suites])
    ax.invert_yaxis()
    ax.set_xlabel("tasks (of 4 per suite)")
    ax.set_xlim(0, max(totals) + 0.5)
    _clean_axes(ax, y=False)
    ax.set_title("Baseline evaluation results by suite (single trial per task)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=3, frameon=False, fontsize=9)
    fig.tight_layout()
    path = out_dir / "suite_results.png"
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def chart_grader_failures(rows: list[dict], unstaged: set[str], out_dir: Path) -> Path:
    genuine: Counter = Counter()
    gap: Counter = Counter()
    for r in rows:
        if r["passed"]:
            continue
        bucket = gap if r["task"] in unstaged else genuine
        for gname, gpassed in r.get("graders", {}).items():
            if not gpassed:
                bucket[gname] += 1

    names = sorted(set(genuine) | set(gap), key=lambda n: -(genuine[n] + gap[n]))
    if not names:
        names, genuine, gap = ["(no grader failures)"], Counter({"(no grader failures)": 0}), Counter()

    fig, ax = plt.subplots(figsize=(9, max(3, 0.6 * len(names) + 1.5)))
    y = range(len(names))
    g_vals = [genuine[n] for n in names]
    u_vals = [gap[n] for n in names]
    ax.barh(y, g_vals, color=CRITICAL, height=0.55, label="Genuine agent failure", zorder=3)
    ax.barh(y, u_vals, left=g_vals, color=GAP, height=0.55,
            label="Failure on an unstaged-fault task", zorder=3)
    for i, (gv, uv) in enumerate(zip(g_vals, u_vals)):
        total = gv + uv
        if total:
            ax.text(total + 0.05, i, str(total), va="center", fontsize=10, color=TEXT)

    ax.set_yticks(list(y))
    ax.set_yticklabels(names, family="monospace", fontsize=10)
    ax.invert_yaxis()
    ax.set_xlabel("trials that failed this grader (of 20)")
    _clean_axes(ax, y=False)
    ax.set_title("Which grader caught each baseline failure")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.15 if len(names) < 6 else -0.08),
              ncol=2, frameon=False, fontsize=9)
    fig.tight_layout()
    path = out_dir / "grader_failures.png"
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def chart_duration_tokens(rows: list[dict], out_dir: Path) -> Path:
    dur = defaultdict(list)
    tok = defaultdict(list)
    for r in rows:
        s = str(r["suite"])
        dur[s].append(float(r.get("duration_s") or 0.0))
        tok[s].append(float(r.get("total_tokens") or 0.0))

    suites = [s for s in SUITE_ORDER if s in dur]
    mean_dur = [sum(dur[s]) / len(dur[s]) for s in suites]
    mean_tok = [sum(tok[s]) / len(tok[s]) for s in suites]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.5))
    for ax, vals, xlabel, fmt in (
        (ax1, mean_dur, "seconds", "{:.1f}s"),
        (ax2, mean_tok, "tokens", "{:.0f}"),
    ):
        y = range(len(suites))
        ax.barh(y, vals, color=BLUE, height=0.6, zorder=3)
        ax.set_yticks(list(y))
        ax.set_yticklabels([SUITE_NAMES[s] for s in suites])
        ax.invert_yaxis()
        ax.set_xlabel(xlabel)
        for i, v in enumerate(vals):
            ax.text(v + max(vals) * 0.015, i, fmt.format(v), va="center", fontsize=9.5, color=TEXT)
        _clean_axes(ax, y=False)
    ax1.set_title("Mean investigation duration by suite")
    ax2.set_title("Mean total tokens by suite")
    fig.tight_layout()
    path = out_dir / "duration_tokens.png"
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("trials", type=Path, help="path to a trials.jsonl file")
    ap.add_argument("--tasks-dir", type=Path,
                     default=Path(__file__).resolve().parent.parent / "src/agent/eval/tasks",
                     help="directory of task YAML files (default: the package tasks dir)")
    ap.add_argument("--out-dir", type=Path, default=Path("docs/pdf/figures"))
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    rows = load(args.trials)
    unstaged = _flagged_unstaged_tasks(args.tasks_dir)

    for fn in (chart_suite_results, chart_grader_failures):
        p = fn(rows, unstaged, args.out_dir)
        print(f"wrote {p}")
    p = chart_duration_tokens(rows, args.out_dir)
    print(f"wrote {p}")


if __name__ == "__main__":
    main()
