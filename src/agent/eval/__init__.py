"""Automated task evaluation harness.

Parses task YAML files and grades observed agent behavior against the
declared expectations using one or more *graders*.

Vocabulary (after Anthropic, "Demystifying evals for AI agents"):
- A *task* is one YAML file under ``agent/eval/tasks/`` (a problem / test case).
- A *trial* is one attempt at a task. The CLI runs N trials per task
  (``--trials N``) and records pass@k / pass^k.
- A *grader* scores one aspect of a trial. A task can have several graders;
  the trial passes only if every applicable grader passes (partial credit:
  the trial score is the fraction of graders that passed).
- A *transcript* is the full event trace of a trial (tool_call / tool_result /
  done), saved to disk per trial.

Built-in graders (code-based) live in :mod:`agent.eval.graders`:
- ``tool_calls``    — the agent called a tool from each expected action's set.
- ``no_raw_markup`` — the summary has no leaked ``<｜｜DSML｜｜>`` XML and no
  raw markdown table rows (Discord renders ``|`` as a wall of pipes).
- ``groundedness``  — each ``expected_evidence`` string appears in the summary
  (coverage); when a transcript is supplied, evidence must also appear in a
  ``tool_result`` event (grounded in observed data, not invented).
- ``no_false_alarm`` — for ``kind: negative`` tasks, the summary does not assert
  a problem (no escalation words). Validates the agent does not over-alarm on
  healthy services.
- ``no_hallucination`` — each ``forbidden_containers`` entry is absent from the
  summary (the agent did not act on a name not in the observed inventory).
- ``right_source``  — for ``kind: logs`` tasks, the declared ``expected_source``
  (loki | docker_logs | either) was called.
- ``right_metric``  — for ``kind: perf`` tasks, the declared metric family was
  queried (inspects PromQL in the transcript).
- ``right_container`` / ``exactly_one`` — ``kind: remediation`` task checks.

The harness (:class:`EvalHarness`) is a *pure checker* — it does not run the
agent. The CLI (:mod:`agent.eval.cli`) is responsible for invoking the
investigation, collecting tool-call names and the summary, then passing them
to :meth:`EvalHarness.evaluate`.

CLI usage::

    python -m agent eval                       # run all tasks, 1 trial each
    python -m agent eval --task api_down        # one task, by name
    python -m agent eval --trials 5 --label qwen2.5-14b   # pass@k / pass^k
"""

from __future__ import annotations

from agent.eval.graders import GraderResult, GRADERS
from agent.eval.harness import (
    EvalHarness,
    EvalResult,
    aggregate_trials,
    discover_tasks,
)
from agent.eval.cli import add_subparser, run

__all__ = [
    "EvalHarness",
    "EvalResult",
    "GraderResult",
    "GRADERS",
    "add_subparser",
    "aggregate_trials",
    "discover_tasks",
    "run",
]
