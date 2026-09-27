import json
import sys
import tomllib
from collections import defaultdict
from pathlib import Path
from statistics import mean

HERE = Path(__file__).parent
SPEC = {t["id"]: t for t in tomllib.loads((HERE / "scenarios.toml").read_text())["task"]}
IDS = sorted(SPEC, key=len, reverse=True)
METRICS = ["correct", "grounded", "valid_tools", "format", "errored", "tool_calls"]


def task_of(path: Path) -> str | None:
    return next((i for part in path.parts for i in IDS if part.startswith(i)), None)


def main() -> None:
    trials: dict[str, list[dict]] = defaultdict(list)
    for reward_file in Path(sys.argv[1]).rglob("reward.json"):
        if task := task_of(reward_file):
            trials[task].append(json.loads(reward_file.read_text()))

    by_category: dict[str, list[dict]] = defaultdict(list)
    consistent: dict[str, list[int]] = defaultdict(list)
    for task, rewards in trials.items():
        category = SPEC[task]["category"]
        by_category[category].extend(rewards)
        by_category["all"].extend(rewards)
        always = int(all(r.get("correct") for r in rewards))
        consistent[category].append(always)
        consistent["all"].append(always)

    print("| category | trials | " + " | ".join(METRICS) + " | consistent |")
    print("|---" * (len(METRICS) + 3) + "|")
    for category in sorted(by_category, key=lambda c: (c == "all", c)):
        rows = by_category[category]
        cells = [f"{mean(r.get(m, 0) for r in rows):.2f}" for m in METRICS]
        print(f"| {category} | {len(rows)} | " + " | ".join(cells) + f" | {mean(consistent[category]):.2f} |")


if __name__ == "__main__":
    main()
