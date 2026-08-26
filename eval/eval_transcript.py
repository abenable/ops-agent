"""Instrumented agent loop shared by the eval/*.ipynb notebooks; dumps the full transcript of every run to eval/logs/."""

import json
import time
from datetime import UTC, datetime
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from langchain.chat_models import init_chat_model

from agent.config.settings import settings

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent
TRANSCRIPT_DIR = _HERE / "logs"

_AGENT_SEEN: dict[str, int] = {}

# Wording a model may use to state a limit; any one of these counts as refusing.
REFUSAL = (
    "cannot", "can't", "unable", "don't have", "do not have",
    "no tool", "no access", "not available", "isn't available",
)

_LIMIT_MESSAGE = (
    "(tool call budget exhausted; this call was not executed. "
    "Answer with what you already have.)"
)

_BUDGET_PROMPT = (
    "You have used the tool budget. Summarize what you found so far, "
    "state the likely cause and next steps, and note what you could not check."
)


def _text(content) -> str:
    """Coerce an LLM message content (str or content-block list) to plain text."""
    if isinstance(content, str):
        return content.strip()
    return "".join(b.get("text", "") for b in content if isinstance(b, dict)).strip()


def _usage(ai: AIMessage) -> dict:
    reported = ai.usage_metadata or {}
    return {
        "input_tokens": reported.get("input_tokens", 0),
        "output_tokens": reported.get("output_tokens", 0),
        "total_tokens": reported.get("total_tokens", 0),
    }


def _serialize_message(msg) -> dict:
    if isinstance(msg, SystemMessage):
        return {"role": "system", "content": msg.content}
    if isinstance(msg, HumanMessage):
        return {"role": "human", "content": msg.content}
    if isinstance(msg, ToolMessage):
        return {"role": "tool", "tool_call_id": msg.tool_call_id, "content": msg.content}
    if isinstance(msg, AIMessage):
        return {
            "role": "ai",
            "content": _text(msg.content),
            "tool_calls": [{"name": c["name"], "args": c["args"]} for c in msg.tool_calls],
        }
    return {"role": "unknown", "content": str(msg)}


def _matches(lowered: str, want) -> bool:
    """A want is a substring, or a tuple/list of alternatives any one of which counts."""
    if isinstance(want, (tuple, list)):
        return any(str(w).lower() in lowered for w in want)
    return str(want).lower() in lowered


def _want_label(want) -> str:
    return " | ".join(str(w) for w in want) if isinstance(want, (tuple, list)) else str(want)


def _grade(
    answer: str,
    expect: list | None,
    tools_called: list[str] | None = None,
    expect_tools: list[str] | None = None,
    forbid_tools: list[str] | None = None,
) -> dict | None:
    """Grade an answer on its text and on which tools the run actually called.

    ``expect`` entries are substrings the answer must contain; an entry that is
    itself a tuple/list passes when any one of its alternatives matches, which is
    what makes refusal wording ("cannot" / "can't" / "unable") gradeable at all.
    ``expect_tools`` and ``forbid_tools`` grade behaviour rather than phrasing,
    and are unaffected by how the model words its answer.
    """
    if not (expect or expect_tools or forbid_tools):
        return None
    lowered = (answer or "").lower()
    called = list(tools_called or [])
    missing = [_want_label(w) for w in (expect or []) if not _matches(lowered, w)]
    missing_tools = [
        _want_label(t)
        for t in (expect_tools or [])
        if not (any(a in called for a in t) if isinstance(t, (tuple, list)) else t in called)
    ]
    forbidden = [t for t in (forbid_tools or []) if t in called]
    return {
        "expect": [_want_label(w) for w in (expect or [])],
        "missing": missing,
        "expect_tools": [_want_label(t) for t in (expect_tools or [])],
        "missing_tools": missing_tools,
        "forbid_tools": list(forbid_tools or []),
        "forbidden_used": forbidden,
        "tools_called": called,
        "passed": not (missing or missing_tools or forbidden),
    }


def _dump_transcript(label: str, question: str, system_prompt: str, tools: list, calls: list, answer: str, total: dict, meta: dict) -> Path:
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    safe_label = label.replace(":", "-").replace("/", "-")
    path = TRANSCRIPT_DIR / f"{stamp}__{safe_label}.json"
    path.write_text(
        json.dumps(
            {
                "label": label,
                "provider": settings.llm_provider,
                "model": settings.llm_model,
                "question": question,
                "system_prompt": system_prompt,
                "tools": [t.name for t in tools],
                "calls": calls,
                "answer": answer,
                "total_usage": total,
                **meta,
            },
            indent=2,
            default=str,
        )
    )
    return path


async def _run_once(
    label: str,
    tools: list,
    system_prompt: str,
    question: str,
    expect: list | None = None,
    expect_tools: list[str] | None = None,
    forbid_tools: list[str] | None = None,
    temperature: float = 0.0,
) -> dict:
    """One graded run: dump the transcript and return answer, grade, and metrics."""
    tools_by_name = {t.name: t for t in tools}
    messages: list = [SystemMessage(content=system_prompt), HumanMessage(content=question)]
    llm = init_chat_model(settings.model_id, temperature=temperature).bind_tools(tools)

    calls: list[dict] = []
    total = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    answer = ""
    error: str | None = None
    failed: dict[tuple, str] = {}
    tool_calls_made = 0
    tool_calls_run = 0
    tool_names: list[str] = []
    turn = 0
    grade: dict | None = None
    meta: dict = {}
    started = time.monotonic()

    try:
        while True:
            turn += 1
            sent = [_serialize_message(m) for m in messages]
            call_started = time.monotonic()
            ai = await llm.ainvoke(messages)
            messages.append(ai)
            usage = _usage(ai)
            for k in total:
                total[k] += usage[k]

            calls.append(
                {
                    "turn": turn,
                    "sent_messages": sent,
                    "response": _serialize_message(ai),
                    "usage": usage,
                    "duration_ms": round((time.monotonic() - call_started) * 1000),
                }
            )
            print(
                f"  [turn {turn}] tokens in={usage['input_tokens']} "
                f"out={usage['output_tokens']} total={usage['total_tokens']}"
            )

            if not ai.tool_calls:
                answer = _text(ai.content)
                break

            budget_spent = False
            tool_results = []
            for tc in ai.tool_calls:
                tool_calls_made += 1
                tool_names.append(tc["name"])
                if tool_calls_made > settings.max_tool_steps:
                    output = _LIMIT_MESSAGE
                    budget_spent = True
                elif tc["name"] not in tools_by_name:
                    output = (
                        f"(no tool named '{tc['name']}' is available; "
                        f"available tools: {', '.join(tools_by_name)})"
                    )
                else:
                    key = (tc["name"], json.dumps(tc["args"], sort_keys=True, default=str))
                    if key in failed:
                        output = f"{failed[key]} — this exact call already failed; try a different tool or approach, or say you cannot answer."
                    else:
                        print(f"    tool call: {tc['name']}({tc['args']})")
                        try:
                            tool_calls_run += 1
                            output = await tools_by_name[tc["name"]].ainvoke(tc["args"])
                        except Exception as exc:  # noqa: BLE001
                            output = f"(tool call failed: {exc})"
                            failed[key] = output
                messages.append(ToolMessage(content=str(output), tool_call_id=tc["id"]))
                tool_results.append({"name": tc["name"], "args": tc["args"], "result": str(output)})
            calls[-1]["tool_results"] = tool_results

            if budget_spent:
                turn += 1
                messages.append(HumanMessage(content=_BUDGET_PROMPT))
                sent = [_serialize_message(m) for m in messages]
                call_started = time.monotonic()
                final = await llm.ainvoke(messages)
                usage = _usage(final)
                for k in total:
                    total[k] += usage[k]
                calls.append(
                    {
                        "turn": turn,
                        "sent_messages": sent,
                        "response": _serialize_message(final),
                        "usage": usage,
                        "duration_ms": round((time.monotonic() - call_started) * 1000),
                        "note": "tool-call-budget summary (harness-added; production ends here instead)",
                    }
                )
                answer = _text(final.content)
                break
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        grade = None if error else _grade(answer, expect, tool_names, expect_tools, forbid_tools)
        meta = {
            "temperature": temperature,
            "duration_ms": round((time.monotonic() - started) * 1000),
            "tool_calls": tool_calls_run,
            "tool_calls_requested": tool_calls_made,
            "tool_names": tool_names,
            "total_tokens": total["total_tokens"],
            "grade": grade,
            "error": error,
        }
        print(
            f"[transcript] {label}: {len(calls)} call(s), {tool_calls_run} tool call(s), "
            f"{meta['duration_ms']}ms — tokens in={total['input_tokens']} "
            f"out={total['output_tokens']} total={total['total_tokens']}"
        )
        if error:
            print(f"[error] {error}")
        if grade:
            print(f"[grade] {_verdict(grade)}")
        path = _dump_transcript(label, question, system_prompt, tools, calls, answer, total, meta)
        shown = path.relative_to(_REPO_ROOT) if path.is_relative_to(_REPO_ROOT) else path
        print(f"[transcript] saved to {shown}")

    return {"answer": answer, "grade": grade, "meta": meta}


def _verdict(grade: dict) -> str:
    """One-line PASS/FAIL naming every reason it failed."""
    if grade["passed"]:
        return "PASS"
    reasons = []
    if grade["missing"]:
        reasons.append("missing text: " + ", ".join(grade["missing"]))
    if grade["missing_tools"]:
        reasons.append("never called: " + ", ".join(grade["missing_tools"]))
    if grade["forbidden_used"]:
        reasons.append("called forbidden: " + ", ".join(grade["forbidden_used"]))
    return "FAIL (" + "; ".join(reasons) + ")"


async def run_eval_loop(
    label: str,
    tools: list,
    system_prompt: str,
    question: str,
    expect: list | None = None,
    expect_tools: list[str] | None = None,
    forbid_tools: list[str] | None = None,
    temperature: float = 0.0,
) -> str:
    """Run `question` through `tools`, dump the transcript, and return the final answer."""
    result = await _run_once(
        label, tools, system_prompt, question, expect, expect_tools, forbid_tools, temperature
    )
    return result["answer"]


async def run_eval_repeats(
    label: str,
    tools: list,
    system_prompt: str,
    question: str,
    expect: list | None = None,
    expect_tools: list[str] | None = None,
    forbid_tools: list[str] | None = None,
    runs: int = 3,
) -> dict:
    """Run the same question `runs` times and report pass@k plus cost spread."""
    results = []
    for i in range(1, runs + 1):
        print(f"--- {label} run {i}/{runs}")
        results.append(
            await _run_once(
                f"{label}#{i}", tools, system_prompt, question,
                expect, expect_tools, forbid_tools,
            )
        )
    return _summarize_runs(label, question, results, runs)


def _summarize_runs(label: str, question: str, results: list[dict], runs: int) -> dict:
    """Aggregate repeated runs into the numbers a report can quote."""
    answers = [r["answer"] for r in results]
    graded = [r["grade"] for r in results if r["grade"]]
    passed = sum(1 for g in graded if g["passed"])
    tokens = [r["meta"].get("total_tokens", 0) for r in results]
    durations = [r["meta"]["duration_ms"] for r in results]
    calls = [r["meta"]["tool_calls"] for r in results]

    summary = {
        "label": label,
        "question": question,
        "runs": runs,
        "graded": len(graded),
        "passed": passed,
        "pass_rate": round(passed / len(graded), 3) if graded else None,
        "distinct_answers": len(set(answers)),
        "tool_calls_mean": round(sum(calls) / len(calls), 2) if calls else 0,
        "total_tokens_mean": round(sum(tokens) / len(tokens)) if tokens else 0,
        "total_tokens_sum": sum(tokens),
        "duration_ms_mean": round(sum(durations) / len(durations)) if durations else 0,
        "duration_ms_max": max(durations) if durations else 0,
    }
    if graded:
        print(f"[repeats] {label}: {passed}/{len(graded)} passed (pass@{runs})")
    print(
        f"[repeats] {label}: {summary['distinct_answers']}/{runs} distinct answers, "
        f"{summary['tool_calls_mean']} tool call(s) mean, "
        f"{summary['total_tokens_mean']} tokens mean, "
        f"{summary['duration_ms_mean']}ms mean"
    )
    return summary


async def run_agent_eval(
    label: str,
    question: str,
    thread_id: str = "notebook",
    expect: list | None = None,
    expect_tools: list[str] | None = None,
    forbid_tools: list[str] | None = None,
) -> str:
    """Same instrumentation, but against the production agent and its memory.

    The isolation notebooks drive a rebuilt loop because their method needs tools
    withheld. This one exercises the deployed configuration instead, so it goes
    through ``get_agent()`` and the real checkpointer; only the messages this call
    added are measured, which is what lets a follow-up on the same thread report
    its own cost rather than the whole thread's.
    """
    from agent.agent import get_agent
    from agent.memory import thread_config

    agent = await get_agent()
    started = time.monotonic()
    final = await agent.ainvoke(
        {"messages": [HumanMessage(content=question)]}, thread_config(thread_id)
    )
    messages = final["messages"]
    seen = _AGENT_SEEN.get(thread_id, 0)
    new = messages[seen:]
    _AGENT_SEEN[thread_id] = len(messages)

    calls: list[dict] = []
    tool_names: list[str] = []
    total = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for turn, m in enumerate(new, start=1):
        usage = _usage(m) if isinstance(m, AIMessage) else None
        if usage:
            for k in total:
                total[k] += usage[k]
        for call in getattr(m, "tool_calls", None) or []:
            tool_names.append(call["name"])
            print(f"    tool call: {call['name']}({call['args']})")
        calls.append({"turn": turn, "response": _serialize_message(m), "usage": usage})

    answer = _text(messages[-1].content)
    grade = _grade(answer, expect, tool_names, expect_tools, forbid_tools)
    meta = {
        "thread_id": thread_id,
        "duration_ms": round((time.monotonic() - started) * 1000),
        "tool_calls": len(tool_names),
        "tool_names": tool_names,
        "new_messages": len(new),
        "grade": grade,
        "error": None,
        "source": "production agent (agent.agent.get_agent)",
    }
    print(
        f"[transcript] {label}: {len(new)} new message(s), {len(tool_names)} tool call(s), "
        f"{meta['duration_ms']}ms — tokens in={total['input_tokens']} "
        f"out={total['output_tokens']} total={total['total_tokens']}"
    )
    if grade:
        print(f"[grade] {_verdict(grade)}")
    path = _dump_transcript(label, question, "(production system prompt)", [], calls, answer, total, meta)
    shown = path.relative_to(_REPO_ROOT) if path.is_relative_to(_REPO_ROOT) else path
    print(f"[transcript] saved to {shown}")
    return answer


def summarize_logs(pattern: str = "*.json") -> list[dict]:
    """Read every dumped transcript back into one row per run, newest last.

    This is the collection step: the notebooks write transcripts, this turns a
    directory of them into the pass counts and cost figures a report quotes.
    """
    rows = []
    for path in sorted(TRANSCRIPT_DIR.glob(pattern)):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        grade = data.get("grade") or {}
        usage = data.get("total_usage") or {}
        rows.append(
            {
                "label": data.get("label", path.stem),
                "model": data.get("model", ""),
                "passed": grade.get("passed"),
                "tool_calls": data.get("tool_calls"),
                "tools": ",".join(data.get("tool_names") or []),
                "total_tokens": usage.get("total_tokens", 0),
                "duration_ms": data.get("duration_ms"),
                "error": data.get("error"),
                "file": path.name,
            }
        )
    return rows


def print_summary(rows: list[dict] | None = None) -> None:
    """Print the collected rows plus the totals worth reporting."""
    rows = summarize_logs() if rows is None else rows
    if not rows:
        print("no transcripts in eval/logs/ yet")
        return
    print(f"{'label':<34}{'pass':<7}{'tools':<7}{'tokens':<9}{'ms':<8}")
    for r in rows:
        verdict = "-" if r["passed"] is None else ("PASS" if r["passed"] else "FAIL")
        print(f"{r['label'][:33]:<34}{verdict:<7}{r['tool_calls']!s:<7}"
              f"{r['total_tokens']!s:<9}{r['duration_ms']!s:<8}")
    graded = [r for r in rows if r["passed"] is not None]
    if graded:
        passed = sum(1 for r in graded if r["passed"])
        print(f"\ngraded {passed}/{len(graded)} passed")
    print(f"total tokens {sum(r['total_tokens'] for r in rows)}, {len(rows)} run(s)")
