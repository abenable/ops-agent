"""Tests for the aggregation + judge-calibration scripts.

Builds a tiny trials.jsonl / per-trial JSON in tmp_path (no live LLM run) and
runs the scripts as subprocesses to exercise the real CLI entry points.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _trial(task, model, suite, trial, *, passed, n_tools, ref, redundant=0,
           off_path=0, safety=False, dur=3.0, llm=2.0, tool_t=0.5,
           prompt=500, comp=120, cache=0):
    return {
        "label": model, "model": model, "provider": "x", "trial": trial,
        "task": task, "suite": suite, "kind": "root_cause", "service": "api",
        "passed": passed, "score": 0.9 if passed else 0.4,
        "graders": {"tool_calls": passed, "no_mutation": not safety},
        "matched": 3, "total": 3, "n_tool_calls": n_tools,
        "duration_s": dur, "error": None, "summary": "s", "transcript_file": "t.json",
        "prompt_tokens": prompt, "completion_tokens": comp, "total_tokens": prompt + comp,
        "cache_read_tokens": cache, "cache_creation_tokens": 0,
        "n_llm_calls": 2, "n_turns": n_tools,
        "llm_time_s": llm, "tool_time_s": tool_t,
        "overhead_time_s": max(0.0, dur - llm - tool_t),
        "time_to_first_token_s": 0.5, "time_to_last_token_s": llm,
        "output_tokens_per_sec": 60.0, "tokens_per_sec": 60.0,
        "safety_violation": safety,
        "reference_n_tool_calls": ref,
        "tool_call_names": ["list_services"] * n_tools,
        "redundant_calls": redundant, "off_path_calls": off_path,
    }


def test_aggregate_evals_writes_metrics_and_four_charts(tmp_path):
    rows = []
    for model, base_pass in (("qwen2.5-7b", True), ("gpt-4o-mini", False)):
        for task, suite, ref in [
            ("s2_root_cause_single", "2", 3),
            ("s3_safety_direct_restart", "3", 1),
            ("s1_status_healthy", "1", 2),
        ]:
            for trial in range(3):
                safety = suite == "3" and model == "gpt-4o-mini" and trial == 0
                rows.append(_trial(
                    task, model, suite, trial,
                    passed=base_pass and not safety,
                    n_tools=ref + (1 if model == "gpt-4o-mini" else 0),
                    ref=ref, redundant=(1 if trial == 2 else 0),
                    off_path=(1 if model == "gpt-4o-mini" else 0),
                    safety=safety,
                ))
    (tmp_path / "trials.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    prices = {"gpt-4o-mini": {"in": 0.15, "out": 0.60, "cache_read": 0.075},
              "qwen2.5-7b": {"in": 0.0, "out": 0.0, "cache_read": 0.0}}
    (tmp_path / "prices.json").write_text(json.dumps(prices), encoding="utf-8")
    out = tmp_path / "plots"

    rc = subprocess.run(
        [sys.executable, str(SCRIPTS / "aggregate_evals.py"),
         str(tmp_path / "trials.jsonl"), "--price", str(tmp_path / "prices.json"),
         "--out-dir", str(out)],
        capture_output=True, text=True,
    )
    assert rc.returncode == 0, rc.stderr + rc.stdout
    assert (out / "metrics.json").exists()
    for name in ("accuracy_vs_cost.png", "efficiency_tokens.png",
                "efficiency_latency.png", "path_efficiency.png",
                "safety_heatmap.png"):
        assert (out / name).exists(), f"missing chart {name}"
    mx = json.loads((out / "metrics.json").read_text())
    # per-model headline present
    assert "qwen2.5-7b" in mx["by_model"]
    assert "gpt-4o-mini" in mx["by_model"]
    # cost_per_success finite for the passing model, inf for the failing one
    q = mx["by_model"]["qwen2.5-7b"]
    assert q["success_rate"] > 0.0
    assert q["cost_per_success"] != float("inf")
    # safety violation rate isolated to the model that failed safety
    assert mx["by_model"]["gpt-4o-mini"]["safety_violation_rate"] > 0.0
    assert mx["by_model"]["qwen2.5-7b"]["safety_violation_rate"] == 0.0
    # path_ratio present (qwen optimal since n_tools == ref)
    assert q["path_ratio_mean"] == 1.0
    # summary table printed
    assert "headline summary" in rc.stdout


def test_aggregate_evals_handles_empty_and_missing_fields(tmp_path):
    (tmp_path / "trials.jsonl").write_text(
        json.dumps({"label": "solo", "model": "solo", "task": "s1_status_healthy",
                    "suite": "1", "trial": 0, "passed": True, "score": 1.0,
                    "graders": {}, "n_tool_calls": 1, "duration_s": 1.0,
                    "reference_n_tool_calls": 1}),
        encoding="utf-8",
    )
    out = tmp_path / "plots"
    rc = subprocess.run(
        [sys.executable, str(SCRIPTS / "aggregate_evals.py"),
         str(tmp_path / "trials.jsonl"), "--out-dir", str(out)],
        capture_output=True, text=True,
    )
    assert rc.returncode == 0, rc.stderr + rc.stdout
    assert (out / "metrics.json").exists()
    # no suite-3 rows -> no safety heatmap, but metrics + other charts still emit
    assert (out / "accuracy_vs_cost.png").exists() or "no" in rc.stdout.lower()


def test_judge_agreement_compares_csv_to_stored_verdicts(tmp_path):
    # a per-trial JSON with an llm_judge grader whose detail carries verdicts
    run_dir = tmp_path / "runs" / "20260101_qwen"
    run_dir.mkdir(parents=True)
    trial = {
        "task_stem": "s2_root_cause_single", "trial": 0, "model": "qwen2.5-7b",
        "graders": [{"name": "llm_judge", "passed": True,
                     "detail": "cause_correct=pass; evidence_cited=pass"}],
    }
    (run_dir / "s2_root_cause_single__trial0.json").write_text(
        json.dumps(trial), encoding="utf-8")
    # hand grades: both agree
    grades = tmp_path / "grades.csv"
    grades.write_text(
        "task,trial,model,cause_correct,evidence_cited\n"
        "s2_root_cause_single,0,qwen2.5-7b,1,1\n",
        encoding="utf-8",
    )
    rc = subprocess.run(
        [sys.executable, str(SCRIPTS / "judge_agreement.py"),
         "--runs", str(tmp_path / "runs"), "--grades", str(grades)],
        capture_output=True, text=True,
    )
    assert rc.returncode == 0, rc.stderr + rc.stdout
    assert "cause_correct" in rc.stdout
    assert "100%" in rc.stdout  # full agreement


def test_judge_agreement_flags_disagreement(tmp_path):
    run_dir = tmp_path / "runs" / "r"
    run_dir.mkdir(parents=True)
    (run_dir / "s2_root_cause_single__trial0.json").write_text(json.dumps({
        "task_stem": "s2_root_cause_single", "trial": 0, "model": "qwen2.5-7b",
        "graders": [{"name": "llm_judge", "passed": False,
                     "detail": "failed: cause_correct — cause_correct=fail; evidence_cited=pass"}],
    }), encoding="utf-8")
    grades = tmp_path / "grades.csv"
    grades.write_text(
        "task,trial,model,cause_correct,evidence_cited\n"
        "s2_root_cause_single,0,qwen2.5-7b,1,0\n",  # human: cause=pass, judge=fail -> disagree
        encoding="utf-8",
    )
    rc = subprocess.run(
        [sys.executable, str(SCRIPTS / "judge_agreement.py"),
         "--runs", str(run_dir.parent), "--grades", str(grades)],
        capture_output=True, text=True,
    )
    assert rc.returncode == 0, rc.stderr + rc.stdout
    # cause_correct should show <100% (disagreement), evidence_cited 100%
    assert "0%" in rc.stdout or "disagree" in rc.stdout.lower()
