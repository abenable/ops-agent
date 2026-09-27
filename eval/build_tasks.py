import json
import shutil
import tomllib
from pathlib import Path

HERE = Path(__file__).parent
TASKS = HERE / "tasks"
INFRA_ENV = {
    "DOCKER_HOST": "tcp://dind:2375",
    "PROMETHEUS_URL": "http://dind:9090",
    "LOKI_URL": "http://dind:3100",
}


def write(path: Path, text: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if executable:
        path.chmod(0o755)


def toml_table(values: dict) -> str:
    return "".join(f"{k} = {json.dumps(v)}\n" for k, v in values.items())


def oracle_solution(question: str, expect: dict) -> str:
    """A canned answer that satisfies the grader: proves environment + grader, not difficulty."""
    answer = "**Likely Cause**\n" + "; ".join(g[0] for g in expect.get("mention_all", []))
    answer += "\n\n**Recommended Action**\nSee above.\n"
    tools = expect.get("tools_any", [])[:1]
    trajectory = [
        {"type": "human", "data": {"content": question}},
        {"type": "ai", "data": {"content": "", "tool_calls": [{"name": t, "args": {}} for t in tools]}},
    ]
    return (
        "mkdir -p /logs/agent/oracle\n"
        f"cat > /logs/agent/oracle/answer.md <<'EOF'\n{answer}EOF\n"
        f"cat > /logs/agent/oracle/trajectory.json <<'EOF'\n{json.dumps(trajectory)}\nEOF\n"
    )


def write_step(root: Path, question: str, expect: dict) -> None:
    write(root / "instruction.md", question + "\n")
    write(root / "tests/expected.json", json.dumps(expect, indent=2))
    shutil.copy(HERE / "grade.py", root / "tests/grade.py")
    write(
        root / "tests/test.sh",
        "#!/bin/bash\npython3 /tests/grade.py /tests/expected.json /logs/agent/oracle\n",
        executable=True,
    )
    write(root / "solution/solve.sh", "#!/bin/bash\n" + oracle_solution(question, expect), executable=True)


def build(task: dict) -> None:
    root = TASKS / task["id"]
    shutil.rmtree(root, ignore_errors=True)
    shutil.copytree(HERE / "env", root / "environment")
    scenario = root / "environment/scenario"
    write(scenario / "compose.yaml", task.get("overlay") or "services: {}\n")
    write(scenario / "inject.sh", task.get("inject", "") + "\n")
    write(
        scenario / "env.sh",
        f"BASELINE_SEC={task.get('baseline_sec', 20)}\nSETTLE_SEC={task.get('settle_sec', 60)}\n",
    )

    steps = task.get("step")
    config = (
        'schema_version = "1.3"\n'
        + ('multi_step_reward_strategy = "mean"\n' if steps else "")
        + "\n[task]\n"
        + toml_table({
            "name": f"marconi/{task['id']}",
            "description": task.get("question") or steps[0]["question"],
            "keywords": [task["category"], task["difficulty"]],
        })
        + "\n[metadata]\n"
        + toml_table({"category": task["category"], "difficulty": task["difficulty"]})
        + "\n[agent]\ntimeout_sec = 300\n\n[verifier]\ntimeout_sec = 60\n"
        + "\n[environment]\nbuild_timeout_sec = 1800\ncpus = 2\nmemory_mb = 4096\n"
        + "\n[environment.env]\n"
        + toml_table(INFRA_ENV | task.get("env", {}))
    )
    if steps:
        for i, step in enumerate(steps, 1):
            config += f'\n[[steps]]\nname = "step-{i}"\n'
            write_step(root / f"steps/step-{i}", step["question"], step["expect"])
    else:
        write_step(root, task["question"], task["expect"])
    write(root / "task.toml", config)


def main() -> None:
    spec = tomllib.loads((HERE / "scenarios.toml").read_text())
    for task in spec["task"]:
        build(task)
    print(f"built {len(spec['task'])} tasks in {TASKS}")


if __name__ == "__main__":
    main()
