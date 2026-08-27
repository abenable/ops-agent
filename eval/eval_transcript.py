import json
import time
from datetime import UTC, datetime
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent.config.settings import settings

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent
TRANSCRIPT_DIR = _HERE / "logs"

_AGENT_SEEN: dict[str, int] = {}


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
        meta = msg.response_metadata or {}
        extra = msg.additional_kwargs or {}
        out = {
            "role": "ai",
            "content": _text(msg.content),
            "tool_calls": [{"name": c["name"], "args": c["args"]} for c in msg.tool_calls],
            "finish_reason": meta.get("finish_reason") or meta.get("stop_reason"),
        }
        # A reasoning model puts its output somewhere _text() does not look. Keep
        # the raw form whenever extraction came back empty, or the tokens that
        # were spent are counted and their content silently thrown away.
        if not out["content"]:
            if not isinstance(msg.content, str):
                out["raw_content"] = msg.content
            for key in ("reasoning_content", "reasoning"):
                if extra.get(key):
                    out[key] = extra[key]
        return out
    return {"role": "unknown", "content": str(msg)}


def _dump_transcript(
    label: str, question: str, system_prompt: str, tool_names: list[str],
    calls: list, answer: str, total: dict, meta: dict, model: str,
) -> Path:
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    safe_label = label.replace(":", "-").replace("/", "-")
    path = TRANSCRIPT_DIR / f"{stamp}__{safe_label}.json"
    path.write_text(
        json.dumps(
            {
                "label": label,
                "model": model,
                "question": question,
                "system_prompt": system_prompt,
                "tools": tool_names,
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


async def run_agent_eval(
    label: str,
    question: str,
    thread_id: str = "notebook",
    tools: list | None = None,
) -> str:
    """Run `question` through the real production agent and dump the transcript."""
    from agent.agent import get_agent
    from agent.memory import thread_config
    from agent.tools import configured_tools

    agent = await get_agent(tools=tools)
    bound_tools = (
        [t if isinstance(t, str) else t.name for t in tools]
        if tools is not None
        else [t.name for t in configured_tools()]
    )
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
    meta = {
        "thread_id": thread_id,
        "duration_ms": round((time.monotonic() - started) * 1000),
        "tool_calls": len(tool_names),
        "tool_names": tool_names,
        "new_messages": len(new),
        "error": None,
        "source": "production agent (agent.agent.get_agent)",
    }
    print(
        f"[transcript] {label}: {len(new)} new message(s), {len(tool_names)} tool call(s), "
        f"{meta['duration_ms']}ms — tokens in={total['input_tokens']} "
        f"out={total['output_tokens']} total={total['total_tokens']}"
    )
    path = _dump_transcript(
        label, question, "(production system prompt)", bound_tools, calls, answer, total, meta, settings.model_id
    )
    shown = path.relative_to(_REPO_ROOT) if path.is_relative_to(_REPO_ROOT) else path
    print(f"[transcript] saved to {shown}")
    return answer


def print_summary(pattern: str = "*.json") -> None:
    """Read every transcript in eval/logs/ and print one row per run plus totals."""
    rows = []
    for path in sorted(TRANSCRIPT_DIR.glob(pattern)):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        usage = data.get("total_usage") or {}
        rows.append(
            {
                "label": data.get("label", path.stem),
                "tool_calls": data.get("tool_calls"),
                "total_tokens": usage.get("total_tokens", 0),
                "duration_ms": data.get("duration_ms"),
            }
        )
    if not rows:
        print("no transcripts in eval/logs/ yet")
        return
    print(f"{'label':<34}{'tools':<7}{'tokens':<9}{'ms':<8}")
    for r in rows:
        print(f"{r['label'][:33]:<34}{r['tool_calls']!s:<7}"
              f"{r['total_tokens']!s:<9}{r['duration_ms']!s:<8}")
    print(f"\ntotal tokens {sum(r['total_tokens'] for r in rows)}, {len(rows)} run(s)")
