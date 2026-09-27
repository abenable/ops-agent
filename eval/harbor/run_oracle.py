import asyncio
import json
import os
import sys
from pathlib import Path

from langchain_core.messages import messages_to_dict

from agent.agent import get_agent
from agent.memory import close_memory, thread_config
from agent.workflows import investigate as workflow

OUT = Path(os.environ.get("ORACLE_OUT", "/logs/agent/oracle"))


async def main() -> None:
    question = sys.stdin.read().strip()
    thread = os.environ.get("ORACLE_THREAD", "harbor")
    if timeout := os.environ.get("ORACLE_TIMEOUT"):
        workflow._INVESTIGATION_TIMEOUT = float(timeout)
    try:
        answer = await workflow.investigate(question, thread_id=thread)
        state = await (await get_agent()).aget_state(thread_config(thread))
        messages = messages_to_dict(state.values.get("messages", []))
    finally:
        await close_memory()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "answer.md").write_text(answer)
    (OUT / "trajectory.json").write_text(json.dumps(messages, default=str, indent=1))
    print(answer)


asyncio.run(main())
