"""Calibrate the opt-in LLM judge against hand-graded transcripts.

NOT a per-run grading path — run once before trusting the judge in CI, then on
a ~5% random sample after a model swap to catch judge drift. High disagreement
means the rubric is ambiguous; tighten the per-criterion question, don't swap
the judge.

Compares hand grades (CSV) against the ``llm_judge`` verdicts stored in the
per-trial JSONs written by ``python -m agent eval --judge``.

Grades CSV (Suite 2 first; one row per trial)::

    task,trial,model,cause_correct,evidence_cited
    s2_root_cause_single,0,qwen2.5-7b,1,1
    s2_root_cause_single,1,qwen2.5-7b,0,1
    s2_root_cause_none,0,qwen2.5-7b,,

A cell of 1 = pass, 0 = fail, blank = skip (not graded). The judge verdicts are
parsed from the ``llm_judge`` grader's detail string (``"<id>=pass|fail|unknown"``).

Usage::

    python scripts/judge_agreement.py --runs src/agent/eval/runs --grades grades.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

_VERDICTS = {"pass": "pass", "fail": "fail", "unknown": "unknown",
             "1": "pass", "0": "fail"}


def _norm(v) -> str | None:
    if v is None or v == "":
        return None
    return _VERDICTS.get(str(v).strip().lower(), "unknown")


def load_judge_verdicts(runs_dir: Path) -> dict[tuple, dict[str, str]]:
    """Index per-trial JSONs by (task, trial, model) -> {criterion: verdict}."""
    index: dict[tuple, dict[str, str]] = {}
    for jf in runs_dir.rglob("*__trial*.json"):
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
        except Exception:
            continue
        task = data.get("task_stem") or Path(data.get("task_file", "")).stem
        trial = data.get("trial")
        model = data.get("model") or data.get("label")
        verdicts: dict[str, str] = {}
        for g in data.get("graders", []):
            if g.get("name") != "llm_judge":
                continue
            # detail looks like: "cause_correct=pass; evidence_cited=fail"
            # or "failed: cause_correct — cause_correct=fail; evidence_cited=pass"
            for cid, v in re.findall(r"(\w[\w_]*)=(pass|fail|unknown)", g.get("detail", "")):
                verdicts[cid] = v
        if verdicts:
            index[(task, trial, model)] = verdicts
    return index


def agree(judge: dict, grades_csv: Path) -> dict:
    rows = list(csv.DictReader(grades_csv.open(encoding="utf-8")))
    criteria = [c for c in (rows[0].keys() if rows else []) if c not in ("task", "trial", "model")]
    per: dict[str, dict] = {c: {"agree": 0, "disagree": 0, "skipped": 0} for c in criteria}
    unmatched = 0
    for row in rows:
        key = (row["task"], int(row["trial"]), row["model"])
        j = judge.get(key)
        if j is None:
            unmatched += 1
            continue
        for c in criteria:
            h = _norm(row.get(c))
            if h is None:
                per[c]["skipped"] += 1
                continue
            jv = j.get(c, "unknown")
            if h == jv:
                per[c]["agree"] += 1
            else:
                per[c]["disagree"] += 1
    # overall agreement per criterion
    out = {}
    for c, d in per.items():
        decided = d["agree"] + d["disagree"]
        out[c] = {
            "agreement": d["agree"] / decided if decided else None,
            "agree": d["agree"], "disagree": d["disagree"], "skipped": d["skipped"],
        }
    out["_unmatched_grade_rows"] = unmatched
    return out


def main():
    ap = argparse.ArgumentParser(description="LLM-judge vs human agreement (calibration).")
    ap.add_argument("--runs", type=Path, default=Path("src/agent/eval/runs"),
                    help="dir of per-trial JSONs (recursive)")
    ap.add_argument("--grades", type=Path, required=True,
                    help="CSV of hand grades (task,trial,model,<criteria...>)")
    args = ap.parse_args()

    judge = load_judge_verdicts(args.runs)
    if not judge:
        print(f"no llm_judge verdicts found under {args.runs}")
        raise SystemExit(1)
    res = agree(judge, args.grades)
    print(f"matched judge verdicts: {len(judge)}; unmatched grade rows: {res['_unmatched_grade_rows']}")
    print(f"{'criterion':24s} {'agree':>6s} {'disagree':>9s} {'skipped':>8s} {'rate':>6s}")
    for c, d in res.items():
        if c.startswith("_"):
            continue
        rate = f"{d['agreement']:.0%}" if d["agreement"] is not None else "n/a"
        print(f"{c:24s} {d['agree']:>6d} {d['disagree']:>9d} {d['skipped']:>8d} {rate:>6s}")


if __name__ == "__main__":
    main()
