# The agent loop

A walkthrough of `src/agent/engine.py` and `src/agent/memory.py`: the LangGraph
tool-calling loop and the conversation state it runs over. These two modules are
generic. They contain no persona, no tool definitions and no Discord types; the
workflows in `src/agent/workflows/` supply all of that per call.

## The graph

Two nodes and one decision.

```text
        START
          |
          v
     +---------+   last message has tool_calls    +---------+
     |  model  | -------------------------------> |  tools  |
     +---------+                                  +---------+
          ^                                            |
          |                                            |
          +--------------------------------------------+
          |
     no tool_calls
          |
          v
         END
```

Built in `_build_graph()`:

```python
graph = StateGraph(MessagesState)
graph.add_node("model", _call_model)
graph.add_node("tools", _call_tools)
graph.add_edge(START, "model")
graph.add_conditional_edges("model", _next_step, {"tools": "tools", END: END})
graph.add_edge("tools", "model")
return graph.compile(checkpointer=saver)
```

State is LangGraph's `MessagesState`, so each node returns `{"messages": [...]}` and
the reducer appends.

**`_call_model`** builds the prompt fresh every turn:

```python
prompt = [SystemMessage(content=system_prompt), *window(state["messages"])]
return {"messages": [await llm.ainvoke(prompt)]}
```

The system prompt is not part of the state. It is prepended on each call, so it can
never be trimmed away by `window()` no matter how long the thread gets, and only the
model's reply is written back.

**`_call_tools`** runs every tool call in the last AIMessage, in order, one await at a
time, and returns one `ToolMessage` per call carrying the matching `tool_call_id`. That
pairing is not optional: an OpenAI-compatible API rejects a request where an
AIMessage's `tool_calls` are not each answered by a `ToolMessage`.

**`_next_step`** is the whole termination condition:

```python
return "tools" if state["messages"][-1].tool_calls else END
```

The loop ends when the model stops asking for tools. There is no "max iterations"
check here; that job belongs to the recursion limit (see below). `run()` then returns
`_text(final["messages"][-1].content)`, which coerces either a plain string or a list
of content blocks to text.

## Per-run objects ride in the config

`run()` builds three things once and hands them down through `RunnableConfig`:

```python
config = thread_config(
    thread_id,
    llm=get_llm().bind_tools(list(tools_by_name.values())),
    tools_by_name=tools_by_name,
    system_prompt=system_prompt,
)
```

`thread_config` (in `memory.py`) merges those into `configurable` alongside the
`thread_id`. The nodes read them back out:

```python
llm = config["configurable"]["llm"]
tools_by_name = config["configurable"]["tools_by_name"]
```

The alternative is building the client and binding the tool schemas inside `_call_model`,
which would repeat that work on every turn of every loop, for no gain: within a single
run the tool set and the prompt do not change. Putting them in the config also keeps the
nodes free of module-level state, which is what lets a test pass a fake tool dict and a
fake LLM into the same compiled graph.

`tools_by_name` is taken as the caller built it rather than rebuilt from a list. Whatever
the caller put in that dict, real tool or test double, is exactly what the loop looks up
by name.

## The compiled graph is cached

```python
_GRAPH: tuple | None = None

async def _graph():
    global _GRAPH
    saver = await checkpointer()
    if _GRAPH is None or _GRAPH[0] is not saver:
        _GRAPH = (saver, _build_graph(saver))
    return _GRAPH[1]
```

Compiling a `StateGraph` is not free, and the graph itself is stateless: the per-run
parts live in the config, and the per-thread parts live in the checkpointer. So one
compiled graph serves every channel and every workflow.

The cache is a `(saver, graph)` tuple rather than a bare graph because the checkpointer
is baked in at compile time. If the saver instance changes, the cached graph is still
writing to the old one, so the identity check (`is not`) forces a rebuild. In practice
this happens in tests, where `tests/conftest.py` swaps in an `InMemorySaver` per test and
resets `engine._GRAPH` to `None`. If you add another module-level cache to this module,
reset it there too.

## The tool budget

`thread_config` sets the limit:

```python
return {
    "configurable": {"thread_id": thread_id or str(uuid4()), **extra},
    # A model turn costs two graph steps (model, then tools).
    "recursion_limit": 2 * settings.max_tool_steps,
}
```

LangGraph's `recursion_limit` counts graph supersteps, not model calls. In this graph a
turn that uses a tool costs two of them: one for `model`, one for `tools`. So a budget
expressed in tool steps has to be doubled to become a recursion limit. With the default
`MAX_TOOL_STEPS=10` the limit is 20, which is about ten rounds of "call a tool, look at
the result".

When the budget runs out, `graph.ainvoke` raises `GraphRecursionError`. `run()` catches
exactly that one exception and calls `_summarize_after_budget`:

```python
state = await (await _graph()).aget_state(config)
messages = [
    SystemMessage(content=system_prompt),
    *window(state.values["messages"]),
    HumanMessage(content=budget_prompt),
]
return _text((await get_llm().ainvoke(messages)).content)
```

Three things to notice.

The thread state is readable after the error because the checkpointer wrote every
superstep as it happened. Everything the model found before it ran out is still there.

The final call uses a bare `get_llm()`, with no tools bound. The model cannot ask for
another tool because it has no tool schemas to ask with, so it has to answer with what
it has. The workflow's `budget_prompt` tells it what to produce; for `investigate.py`
that is a summary, a likely cause, next steps, and a note on what it could not check.

That last call goes straight to the LLM, not through the graph, so neither the budget
prompt nor the summary is checkpointed. A follow-up question in the same thread sees
the full tool transcript but not the summary the user was shown.

If the summary call itself fails, the exception propagates out of `run()`. The workflow
catches it (`investigate()` returns `"Investigation failed: ..."`), so the user still
gets a reply.

## Errors inside the loop

`_call_tools` never lets a tool failure escape:

```python
tool = tools_by_name.get(call["name"])
if tool is None:
    output = f"(unknown tool '{call['name']}')"
else:
    try:
        output = await tool.ainvoke(call["args"])
    except Exception as exc:
        output = f"(tool '{call['name']}' failed: {exc})"
results.append(ToolMessage(content=str(output), tool_call_id=call["id"]))
```

Both failure modes become a `ToolMessage` like any successful result, so the model reads
them on the next turn and can react: retry with different arguments, try another tool, or
report that it could not check something. A hallucinated tool name (small models invent
them) costs one turn rather than killing the run, and a Prometheus that is down turns
into an answer that says Prometheus is down.

Every tool call is logged at INFO before it runs (`logger.info("tool call: %s(%s)", ...)`),
which is what shows up in the Discord log channel when `DISCORD_LOG_CHANNEL_ID` is set.

The model node is deliberately not wrapped. A timeout or a connection error from the LLM
propagates out of `run()` to the workflow, which turns it into a message for the user.
There is nothing useful the loop could do with it.

## Conversation memory

`src/agent/memory.py` holds one conversation per `thread_id`, replayed on every call.
Callers decide what a thread is: `workflows/nl.py` and the `/investigate` command both
use the Discord channel id, so a slash command and a follow-up mention in the same
channel are the same conversation. `workflows/report.py` passes no thread id and gets a
`uuid4()` one-shot.

### The checkpointer is opened lazily, inside the running loop

```python
async def checkpointer():
    global _CHECKPOINTER, _STACK
    if _CHECKPOINTER is None:
        _STACK = AsyncExitStack()
        _CHECKPOINTER = await _STACK.enter_async_context(
            AsyncSqliteSaver.from_conn_string(str(DB_PATH))
        )
        await _CHECKPOINTER.setup()
    return _CHECKPOINTER
```

`AsyncSqliteSaver` owns an `aiosqlite` connection that is bound to the event loop it was
opened in, so it cannot be a module-level constant built at import time. It is created on
first use, which is always inside the discord.py loop, and held open in an
`AsyncExitStack` for the life of the process.

`setup()` is called up front rather than left to the first write. Most saver entry points
create their tables on demand, but `adelete_thread` does not, and that is the one behind
`/reset`. Without the explicit `setup()`, `/reset` on a fresh database fails against
tables that do not exist yet.

Tests set `_CHECKPOINTER` directly to an `InMemorySaver`, which this function returns
as-is.

### close_memory() must run before the loop ends

```python
async def close_memory() -> None:
    global _CHECKPOINTER, _STACK
    if _STACK is not None:
        await _STACK.aclose()
    _CHECKPOINTER = _STACK = None
```

`aiosqlite` runs its connection on a worker thread that keeps blocking on its queue after
the event loop closes. Skip this and the process does not exit: it hangs, so `docker stop`
waits out its grace period and sends SIGKILL. That is the entire reason `_Bot` in
`src/agent/bot/client.py` subclasses `commands.Bot`:

```python
class _Bot(commands.Bot):
    async def close(self) -> None:
        await close_memory()
        await super().close()
```

Anything else that opens the checkpointer (a script, a notebook) has the same obligation.

### The context window

```python
def window(messages: list[BaseMessage]) -> list[BaseMessage]:
    return trim_messages(
        messages,
        max_tokens=settings.max_context_tokens,
        token_counter="approximate",
        start_on="human",
        end_on=("human", "tool"),
    )
```

A remembered thread grows without bound, so it is trimmed before every model call, in
`_call_model` and again in `_summarize_after_budget`. `trim_messages` keeps the tail by
default. The counter is `"approximate"`, so trimming does not need a tokenizer for
whatever model the OpenAI-compatible endpoint happens to be serving.

`start_on` and `end_on` are the load-bearing arguments, and they are about protocol
validity, not tidiness. An AIMessage with `tool_calls` and the `ToolMessage`s answering
it are one indivisible unit to an OpenAI-compatible API. Cut between them in either
direction and the next request is a 400:

- Without `start_on="human"`, a window could begin with a `ToolMessage` whose AIMessage
  was trimmed off. That is a tool result answering a call the server never saw.
- Without `end_on=("human", "tool")`, a window could end with an AIMessage carrying
  `tool_calls` that have no results after them. That is an unanswered tool call.

The cost of getting this right is that trimming works in whole exchanges, so a thread
that outgrows `MAX_CONTEXT_TOKENS` drops its oldest turns wholesale. A large seeded
digest is the first thing evicted.

### Reading and dropping a thread

`history(thread_id)` fetches the checkpoint and returns
`checkpoint["channel_values"].get("messages", [])`, or `[]` if the thread has never run.
`forget(thread_id)` calls `saver.adelete_thread(thread_id)`, which takes the raw id
rather than a config. `/reset` is a one-line call to it.

### seed()

```python
async def seed(thread_id: str, content: str) -> None:
    graph = await _graph()
    await graph.aupdate_state(
        thread_config(thread_id), {"messages": [HumanMessage(content=content)]}, as_node=START
    )
```

This pre-loads a thread with content that did not come from a model turn. `bot/digest.py`
calls it after posting a scheduled report, using the id `post_report()` returned (the new
forum thread's id, or the text channel's id). Someone can then @mention the bot under the
posted report and it already has the report in context instead of re-deriving it.

`as_node=START` writes the update as if it came from the entry point, so the messages
reducer appends it without running a node.

The message type matters. It is a `HumanMessage`, not an `AIMessage`, because `window()`
trims with `start_on="human"`: a thread whose only content is a leading `AIMessage` gets
trimmed to nothing before it ever reaches the model, and the seed would silently
disappear. A `HumanMessage` is the only type guaranteed to survive as the first message
of a fresh thread.

## One run, end to end

A `/investigate` call on a channel that already has history:

```text
run(question, tools_by_name, system_prompt, budget_prompt, thread_id="123")
  |
  |  thread_config -> {"configurable": {thread_id, llm, tools_by_name, system_prompt},
  |                    "recursion_limit": 20}
  |  _graph()      -> cached graph, compiled against the AsyncSqliteSaver
  v
graph.ainvoke({"messages": [HumanMessage(question)]}, config)
  |
  |  checkpointer loads thread "123" and appends the new question
  v
step 1  model : [SystemMessage] + window(history + question) -> AIMessage(tool_calls=[docker_status])
step 2  tools : docker_status(container="api") -> ToolMessage
step 3  model : ... -> AIMessage(tool_calls=[query_loki_range])
step 4  tools : query_loki_range(...) -> ToolMessage
step 5  model : ... -> AIMessage(content="**Likely cause** ...")   no tool_calls
  |
  v
_next_step -> END, run() returns _text(last message)
```

Every step is checkpointed as it happens, which is both how the next message in the
channel picks up the context and how `_summarize_after_budget` can read back the
transcript after a `GraphRecursionError` at step 20.
