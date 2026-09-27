import json
import re
import sys
from pathlib import Path

KNOWN_TOOLS = {
    "list_services", "docker_status", "docker_logs",
    "list_metric_names", "get_label_values", "query_prometheus", "query_prometheus_range",
    "get_loki_label_values", "query_loki", "query_loki_range",
}
FAILURE_PREFIXES = (
    "investigation timed out", "investigation failed", "model call failed",
    "the model returned an empty answer", "tool call limit reached",
)


def this_turn_calls(messages: list[dict]) -> list[str]:
    last_human = max((i for i, m in enumerate(messages) if m["type"] == "human"), default=-1)
    return [
        call["name"]
        for m in messages[last_human + 1 :]
        if m["type"] == "ai"
        for call in m["data"].get("tool_calls") or []
    ]


def mentions(text: str, phrase: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(phrase.lower()), text) is not None


def grade(expect: dict, answer: str, calls: list[str]) -> dict:
    text = answer.lower()
    available = set(expect.get("available_tools", KNOWN_TOOLS))
    tools_any = expect.get("tools_any")
    correct = all(
        any(mentions(text, s) for s in group) for group in expect.get("mention_all", [])
    ) and not any(mentions(text, s) for s in expect.get("mention_none", []))
    return {
        "correct": int(correct),
        "grounded": int(not tools_any or any(c in tools_any for c in calls)),
        "valid_tools": int(all(c in available for c in calls)),
        "format": int(not expect.get("sections") or ("likely cause" in text and "recommended action" in text)),
        "errored": int(not text.strip() or text.strip().startswith(FAILURE_PREFIXES)),
        "tool_calls": len(calls),
    }


def main() -> None:
    expect = json.loads(Path(sys.argv[1]).read_text())
    out = Path(sys.argv[2])
    answer_file, trajectory_file = out / "answer.md", out / "trajectory.json"
    answer = answer_file.read_text() if answer_file.exists() else ""
    calls = this_turn_calls(json.loads(trajectory_file.read_text())) if trajectory_file.exists() else []
    reward = grade(expect, answer, calls)
    Path("/logs/verifier").mkdir(parents=True, exist_ok=True)
    Path("/logs/verifier/reward.json").write_text(json.dumps(reward))
    print(json.dumps(reward))


if __name__ == "__main__":
    main()
