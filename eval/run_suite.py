"""Run every notebook's eval cases against the active model, sequentially.

Usage: run_suite.py [--runs N] [label-substring ...]
       --runs N repeats every case N times (default 1); one run proves nothing.
       label substrings filter which cases run (default: all).
Model is chosen via LLM_PROVIDER/LLM_MODEL env vars, like production.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_transcript import run_agent_eval  # noqa: E402
from agent.tools.docker import docker_logs, docker_status, list_services  # noqa: E402
from agent.tools.loki import get_loki_label_values, query_loki, query_loki_range  # noqa: E402
from agent.tools.prometheus import (  # noqa: E402
    get_label_values,
    list_metric_names,
    query_prometheus,
    query_prometheus_range,
)

PROM_TOOLS = [list_metric_names, get_label_values, query_prometheus]
PROM_RANGE_TOOLS = [list_metric_names, get_label_values, query_prometheus_range]
LOKI_TOOLS = [get_loki_label_values, query_loki]
LOKI_RANGE_TOOLS = [get_loki_label_values, query_loki_range]

CASES = [
    ("01_list_services:live-inscope", "What containers and monitored endpoints exist in this lab?", [list_services], False),
    ("01_list_services:live-outofscope", "Is the agent-api container currently healthy?", [list_services], False),
    ("02_docker_status:live-inscope", "Is the container named 'agent-api' currently running?", [docker_status], False),
    ("02_docker_status:live-outofscope", "What do the recent logs for agent-api say?", [docker_status], False),
    ("03_docker_logs:live-inscope", "Show me the last 50 log lines for the container 'agent-api'.", [docker_logs], False),
    ("03_docker_logs:live-outofscope", "Is the agent-api container currently healthy?", [docker_logs], False),
    ("04_query_prometheus:live-inscope", "What is the current value of the 'up' metric?", PROM_TOOLS, False),
    ("04_query_prometheus:live-outofscope", "How has CPU usage trended over the last 30 minutes?", PROM_TOOLS, False),
    ("05_query_prometheus_range:live-inscope", "How has the 'up' metric trended over the last 30 minutes?", PROM_RANGE_TOOLS, False),
    ("05_query_prometheus_range:live-outofscope", "Show me the error logs from the last 15 minutes.", PROM_RANGE_TOOLS, False),
    ("06_query_loki:live-inscope", "Show recent error logs across all services.", LOKI_TOOLS, False),
    ("06_query_loki:live-outofscope", "What is the current CPU usage of the grafana container?", LOKI_TOOLS, False),
    ("07_query_loki_range:live-inscope", "Show error logs from the last 15 minutes.", LOKI_RANGE_TOOLS, False),
    ("07_query_loki_range:live-outofscope", "Is the agent-api container currently healthy?", LOKI_RANGE_TOOLS, False),
    ("08_all_tools:broad", "Is anything wrong in the lab right now?", None, False, "notebook"),
    ("08_all_tools:followup-same-thread", "Why? Show me the evidence for that.", None, True, "notebook"),
    ("08_all_tools:followup-fresh-thread", "Why? Show me the evidence for that.", None, False, "fresh"),
]


def _parse_args(argv: list[str]) -> tuple[int, list[str]]:
    runs, filters = 1, []
    it = iter(argv)
    for arg in it:
        if arg == "--runs":
            runs = int(next(it))
        elif arg.startswith("--runs="):
            runs = int(arg.split("=", 1)[1])
        else:
            filters.append(arg)
    return runs, filters


async def main() -> None:
    runs, filters = _parse_args(sys.argv[1:])
    for rep in range(1, runs + 1):
        if runs > 1:
            print(f"\n######## repetition {rep}/{runs} ########", flush=True)
        for case in CASES:
            label, question, tools, resume = case[:4]
            thread_id = case[4] if len(case) > 4 else label
            if filters and not any(f in label for f in filters):
                continue
            print(f"\n=== {label} ===", flush=True)
            try:
                answer = await run_agent_eval(
                    label,
                    question,
                    thread_id=f"{thread_id}#r{rep}",
                    tools=tools,
                    resume=resume,
                )
                print(f"ANSWER: {answer[:300]}", flush=True)
            except Exception as exc:
                print(f"ERROR: {exc!r}", flush=True)


asyncio.run(main())
