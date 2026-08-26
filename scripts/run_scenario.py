"""Stage a controlled infrastructure fault and check what the agent says about it.

Deliberately a standalone operator script, not an agent tool. It creates and
stops containers, and nothing the model can reach is allowed to do that: the
read-only guarantee is that no such call exists in the tool table.
"""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx2 as httpx

from agent.config.settings import settings
from agent.tools.docker import _docker_available, _docker_client
from agent.workflows.investigate import investigate

TARGET = "marconi-scenario-target"
IMAGE = "alpine:3.20"
RESULTS_DIR = Path(__file__).resolve().parents[1] / "eval" / "results" / "scenarios"

SCENARIOS = {
    "healthy": {
        "stop": False,
        "question": f"Is the container `{TARGET}` healthy right now?",
        "expect_any": ["running", "up", "healthy"],
        "reject_any": ["exited", "stopped", "not running"],
    },
    "container_down": {
        "stop": True,
        "question": f"Is the container `{TARGET}` healthy right now?",
        "expect_any": ["exited", "stopped", "not running", "down"],
        "reject_any": [],
    },
}


async def _api(method: str, path: str, **kwargs) -> httpx.Response:
    async with _docker_client() as client:
        return await client.request(method, f"/v1.43{path}", **kwargs)


async def _remove_target() -> None:
    await _api("DELETE", f"/containers/{TARGET}", params={"force": "true", "v": "true"})


async def _create_target() -> None:
    await _remove_target()
    body = {"Image": IMAGE, "Cmd": ["sleep", "600"], "Labels": {"marconi.scenario": "true"}}
    created = await _api("POST", "/containers/create", params={"name": TARGET}, json=body)
    if created.status_code == 404:
        pull = await _api("POST", "/images/create", params={"fromImage": IMAGE}, timeout=120)
        pull.raise_for_status()
        created = await _api("POST", "/containers/create", params={"name": TARGET}, json=body)
    created.raise_for_status()
    started = await _api("POST", f"/containers/{TARGET}/start")
    started.raise_for_status()


async def _stop_target() -> None:
    stopped = await _api("POST", f"/containers/{TARGET}/stop", params={"t": "0"})
    stopped.raise_for_status()


def _grade(answer: str, spec: dict) -> dict:
    lowered = answer.lower()
    matched = [w for w in spec["expect_any"] if w in lowered]
    rejected = [w for w in spec["reject_any"] if w in lowered]
    return {
        "passed": bool(matched) and not rejected,
        "matched": matched,
        "rejected": rejected,
    }


async def _announce(name: str, result: dict) -> None:
    channel_id = settings.discord_test_scenarios_channel_id
    if not (channel_id and settings.discord_bot_token):
        return
    verdict = "PASS" if result["passed"] else "FAIL"
    content = (
        f"**Scenario `{name}` — {verdict}**\n"
        f"matched: {', '.join(result['matched']) or 'nothing'}\n"
        f"> {result['answer'][:1500]}"
    )
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            headers={"Authorization": f"Bot {settings.discord_bot_token}"},
            json={"content": content[:1900]},
        )
    if response.status_code >= 400:
        print(f"[warn] could not post to scenarios channel: {response.status_code}", file=sys.stderr)


async def run(name: str, keep: bool) -> dict:
    spec = SCENARIOS[name]
    print(f"[scenario] {name}: staging {TARGET}")
    await _create_target()
    try:
        if spec["stop"]:
            await _stop_target()
            print(f"[scenario] stopped {TARGET}")
        print(f"[scenario] asking: {spec['question']}")
        answer = await investigate(spec["question"], thread_id=f"scenario-{name}")
        result = {"scenario": name, "at": datetime.now(UTC).isoformat(),
                  "question": spec["question"], "answer": answer, **_grade(answer, spec)}
    finally:
        if not keep:
            await _remove_target()
            print(f"[scenario] cleaned up {TARGET}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    (RESULTS_DIR / f"{stamp}__{name}.json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"[scenario] {name}: {'PASS' if result['passed'] else 'FAIL'} "
          f"(matched {result['matched'] or 'nothing'}"
          f"{', wrongly said ' + ', '.join(result['rejected']) if result['rejected'] else ''})")
    await _announce(name, result)
    return result


async def main_async(names: list[str], keep: bool) -> int:
    if not _docker_available():
        print("docker socket unavailable", file=sys.stderr)
        return 2
    results = [await run(name, keep) for name in names]
    passed = sum(1 for r in results if r["passed"])
    print(f"\n[scenario] {passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run staged infrastructure scenarios")
    parser.add_argument("scenario", nargs="?", choices=[*SCENARIOS, "all"], default="all")
    parser.add_argument("--keep", action="store_true", help="leave the container in place")
    args = parser.parse_args()
    names = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    return asyncio.run(main_async(names, args.keep))


if __name__ == "__main__":
    sys.exit(main())
