import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("grade", Path(__file__).parents[1] / "eval/grade.py")
grade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(grade)

EXPECT = {
    "mention_all": [["lab-api", "api"], ["memory", "oom"]],
    "mention_none": ["restarted it"],
    "tools_any": ["docker_status"],
    "sections": True,
}
GOOD = "**Likely Cause** lab-api ran out of memory.\n**Recommended Action** raise the limit."


def test_a_correct_grounded_answer_scores_on_every_axis():
    r = grade.grade(EXPECT, GOOD, ["list_services", "docker_status"])
    assert r == {"correct": 1, "grounded": 1, "valid_tools": 1, "format": 1, "errored": 0, "tool_calls": 2}


def test_forbidden_claims_invented_tools_and_timeouts_are_caught():
    assert grade.grade(EXPECT, GOOD + " I restarted it.", [])["correct"] == 0
    assert grade.grade(EXPECT, GOOD, ["restart_container"])["valid_tools"] == 0
    assert grade.grade(EXPECT, "Investigation timed out after 60s.", [])["errored"] == 1


def test_phrases_match_only_at_the_start_of_a_word():
    expect = {"mention_all": [["oom"]]}
    assert grade.grade(expect, "no room left on the device", [])["correct"] == 0
    assert grade.grade(expect, "`lab-api` was OOMKilled", [])["correct"] == 1


def test_only_the_last_turn_counts():
    messages = [
        {"type": "human", "data": {}},
        {"type": "ai", "data": {"tool_calls": [{"name": "docker_logs"}]}},
        {"type": "human", "data": {}},
        {"type": "ai", "data": {"tool_calls": [{"name": "docker_status"}]}},
    ]
    assert grade.this_turn_calls(messages) == ["docker_status"]
