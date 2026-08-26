# Development

## Setup

```bash
uv sync                    # includes the dev group (pytest, ipykernel)
cp .env.example .env
uv run pytest              # 89 tests, ~3s
uv run agent bot
```

Python 3.13+. Packaging is setuptools with `package-dir = {"" = "src"}`; the
console script `agent = agent.__main__:main` is what makes `agent bot` work.

## Layout

```
src/agent/
  __main__.py       CLI entry: `agent bot` and `python -m agent bot`
  agent.py          the agent: one create_agent call, cached
  memory.py         SQLite checkpointer, thread_config
  normalize.py      separator-agnostic name matching, AmbiguousName
  config/settings.py  pydantic-settings, DB paths, provider env export
  tools/            the 10 read-only tools: docker, prometheus, loki
  workflows/        investigate, report, nl: question in, answer out
  bot/              slash commands, mentions, monitor, digests, status, client
  alerting/         Discord embeds for alerts and reports
  watchlist/        SQLite repository: watch list + event log
eval/               eval notebooks + eval_transcript.py harness
tests/              pytest suite
scripts/            eval-dataset build helpers
```

### Boundaries worth keeping

`agent.py` is the only place an agent is constructed. Workflows import
`get_agent()` rather than calling `create_agent` themselves.

Neither `agent.py` nor `memory.py` imports `agent.bot`. The agent knows nothing
about Discord, and the bot layer does the formatting.

`memory.py` is the only opener of `memory.db`. Anything else that wants
conversation state goes through `thread_config` and the agent.

`eval/eval_transcript.py` sits beside the notebooks rather than in the package,
because it is eval harness and not shipped code.

## Tests

```bash
uv run pytest                      # the default suite
uv run pytest -m integration       # live LLM + Discord checks, excluded by default
uv run pytest tests/test_investigate.py -v
```

Integration tests hit real endpoints and are deselected by `addopts` in
`pyproject.toml`. There are two: the LLM endpoint and the Discord token.

### How the agent is faked

`tests/conftest.py` holds the shared seam. `use_fake_llm(monkeypatch, llm)`
patches `init_chat_model` in all three places it is bound: `agent.agent`, where
the client is built, plus `langchain.agents.factory` and
`langchain.agents.middleware.summarization` inside the library. The factory is
the seam rather than a client object, so a fake needs no provider wiring.

The fakes are there too: `QueueLLM` (replays a script), `FlatLLM` (answers at
once), `RecordingLLM` (captures what the model was handed), `DeadLLM` (fails),
`LoopLLM` (never stops calling tools, to drive the budget).

An autouse fixture points both SQLite paths at `tmp_path`, swaps the
checkpointer for an `InMemorySaver`, and resets the cached agent so each test
builds against its own saver and patched tools.

To swap a single tool, use `monkeypatch.setitem(agent_mod._TOOLS_BY_NAME, ...)`.
The dict exists for exactly that.

| File | Covers |
|---|---|
| `test_investigate.py` | Tool call then answer, no-tool answer, a raising tool fed back, the tool-call limit, LLM failure, the report template, thread isolation |
| `test_memory.py` | `thread_config`, and a thread surviving a closed connection |
| `test_eval_transcript.py` | The eval harness: budget counting, crash transcripts, unknown tools, grading |
| `test_monitor.py` | Baseline vs transition, scope, pruning, endpoint probes, event logging |
| `test_digest.py` | Daily/weekly bodies, downtime pairing, flap narrative, scheduling, status snapshots |
| `test_docker_tools.py`, `test_services.py`, `test_normalize.py` | Tool behaviour, HTTP clients, name matching |
| `test_summarize.py`, `test_alerting.py`, `test_bot.py`, `test_nl.py`, `test_watchlist.py` | Discord formatting, embeds, command wiring, mentions, the watch list |

## Conventions

- Comments explain why, not what. A comment earns its place by recording a
  constraint that is not visible in the code, such as a Discord limit, a
  provider quirk, or the bug that motivated a line.
- Prefer the framework's mechanism over a hand-rolled one. The middleware stack
  replaced a custom loop, budget, and trimmer.
- Read-only stays read-only. A mutating tool would make this a different system.

## Adding a tool

1. Write it in `agent/tools/<backend>.py` with `@tool` and a description that
   says when to use it and what to call first.
2. Add it to `ALL_TOOLS` in `agent/tools/__init__.py`.
3. Clamp anything unbounded: window, limit, tail.
4. Test it in `tests/test_docker_tools.py` or a sibling.

It is picked up automatically: `agent.py` builds its tool list from `ALL_TOOLS`.
