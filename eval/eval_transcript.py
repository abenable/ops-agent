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


def _grade(answer: str, expect: list[str] | None) -> dict | None:
    """Check an answer against the substrings it must contain."""
    if not expect:
        return None
    lowered = answer.lower()
    missing = [s for s in expect if s.lower() not in lowered]
    return {"expect": expect, "missing": missing, "passed": not missing}


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


async def run_eval_loop(
    label: str,
    tools: list,
    system_prompt: str,
    question: str,
    expect: list[str] | None = None,
    temperature: float = 0.0,
) -> str:
    """Run `question` through `tools` bound to the configured LLM, dump the transcript, and return the final answer."""
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
    turn = 0
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
        grade = None if error else _grade(answer, expect)
        meta = {
            "temperature": temperature,
            "duration_ms": round((time.monotonic() - started) * 1000),
            "tool_calls": tool_calls_run,
            "tool_calls_requested": tool_calls_made,
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
            verdict = "PASS" if grade["passed"] else f"FAIL (missing: {', '.join(grade['missing'])})"
            print(f"[grade] {verdict}")
        path = _dump_transcript(label, question, system_prompt, tools, calls, answer, total, meta)
        shown = path.relative_to(_REPO_ROOT) if path.is_relative_to(_REPO_ROOT) else path
        print(f"[transcript] saved to {shown}")

    return answer


async def run_eval_repeats(
    label: str,
    tools: list,
    system_prompt: str,
    question: str,
    expect: list[str] | None = None,
    runs: int = 3,
) -> list[str]:
    """Run the same question `runs` times and report how consistent the answers are."""
    answers = []
    for i in range(1, runs + 1):
        print(f"--- {label} run {i}/{runs}")
        answers.append(await run_eval_loop(f"{label}#{i}", tools, system_prompt, question, expect))
    if expect:
        passed = sum(bool(_grade(a, expect)["passed"]) for a in answers)
        print(f"[repeats] {label}: {passed}/{runs} passed")
    print(f"[repeats] {label}: {len(set(answers))}/{runs} distinct answers")
    return answers
