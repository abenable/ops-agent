# Development

## Layout and packaging

The project uses a src layout. `pyproject.toml` sets
`[tool.setuptools] package-dir = {"" = "src"}` and discovers packages under `src/`, so
the importable package is `agent` and nothing in the repo root shadows it. The build
backend is setuptools; the console script `agent = agent.cli:main` is what `agent bot`
resolves to, and `python -m agent bot` reaches the same `main()` through
`src/agent/__main__.py`.

```
src/agent/     the package
tests/         pytest suite, offline by default
eval/          Jupyter notebooks that exercise the tools against a live LLM
data/          SQLite file (agent.db), created on first use
docs/          this documentation
```

`README.md` is referenced by `pyproject.toml` as the readme and is copied by the
Dockerfile before dependencies are installed, so it has to exist for the image to build.

Layer boundaries worth keeping: `engine.py` imports neither `agent.tools` nor anything
Discord, workflows contain no Discord types, and `bot/` is the only place that knows
about interactions and channels.

## Setting up

```bash
uv sync
```

That creates `.venv`, installs the project in editable form and installs the `dev`
group (`pytest`, `ipykernel`). Then:

```bash
cp .env.example .env
```

Settings are read by `src/agent/config/settings.py` through pydantic-settings, with the
`.env` file located via `find_dotenv`, so you can run commands from any directory in
the repo. `DATABASE_URL` is resolved to an absolute `DB_PATH` relative to the repo root
and its parent directory is created at import time.

Run the bot locally:

```bash
uv run python -m agent bot
```

## Running the tests

```bash
uv run pytest
```

The default run is fully offline. There is no network access, no Docker socket, no
Discord gateway and no LLM call anywhere in it: Docker responses are patched with
`AsyncMock`, the LLM is replaced with small fake classes that play back a queue of
`AIMessage` objects, and Discord objects are `MagicMock`/`AsyncMock` stand-ins.

`pyproject.toml` sets `addopts = "-m 'not integration'"`, so tests marked
`@pytest.mark.integration` are deselected by default. Run them explicitly:

```bash
uv run pytest -m integration
```

Three tests carry the marker. `tests/test_llm.py::test_llm_connection_and_api_key` does
a real chat completion against `LLM_BASE_URL` and skips if `LLM_API_KEY` is unset or
still the placeholder. `tests/test_discord_token.py::test_discord_bot_token_valid` hits
Discord's `/users/@me` with the configured token and skips if the token is unset.
`tests/test_monitor.py::test_demo_incident_scenario_end_to_end` is marked integration as
a scripted end-to-end demo scenario, but it drives fake Docker responses and needs
nothing live.

`tests/conftest.py` holds one autouse fixture, `tmp_database`, which runs for every
test and does three things:

1. Points `watchlist.repository.DB_PATH` and `memory.DB_PATH` at a file under pytest's
   `tmp_path`, so no test can write to the real `data/agent.db`.
2. Replaces `memory._CHECKPOINTER` with an `InMemorySaver`. The real `AsyncSqliteSaver`
   owns an aiosqlite connection bound to the loop it was opened in, and each test drives
   its own `asyncio.run`, so a shared real saver would have to be closed inside every
   test or the process hangs at exit. Actual SQLite persistence is covered separately by
   `test_memory_persists_across_connections`, which builds its own saver.
3. Resets `engine._GRAPH` to `None`, so the compiled graph is rebuilt against this
   test's checkpointer instead of being reused from a previous test.

The fixture returns the temp path, so a test that wants it can take `tmp_database` as an
argument.

### What each test file covers

| File | Area |
| --- | --- |
| `tests/test_investigate.py` | The engine loop: tool call then answer, answering with no tools, a raising tool fed back as text, the step cap triggering the final summary, an LLM failure returning a message, thread isolation, and the report template. |
| `tests/test_memory.py` | `history`/`forget` roundtrip, seeding a thread, seeded content actually reaching the model, one-shot thread config, and persistence across two connections. |
| `tests/test_monitor.py` | Endpoint parsing, container transition edges, no alert on the first poll after a restart, recovery alerts to the status channel, scope from filter plus watch list, pruning out-of-scope state, endpoint probes, and the demo incident scenario. |
| `tests/test_digest.py` | Daily and weekly rendering, pairing events into outages and downtime, still-down accounting, the flap narrative, weekday gating, the reports-channel gate, and thread seeding after posting. |
| `tests/test_summarize.py` | `clean()` fallbacks when the LLM is empty or raises, service-name sanitizing, length caps, and `discordify` heading and table conversion including code-fence exclusion. |
| `tests/test_normalize.py` | `normalize()`, container matching across separators, exact match beating a substring, and ambiguity raising in both container and watch-list lookups. |
| `tests/test_services.py` | The Prometheus and Loki clients: bearer token only when configured, label-name validation, Loki's instant query going through the range endpoint, container name handling, and Docker stream demuxing. |
| `tests/test_docker_tools.py` | The `docker_status` and `docker_logs` tools: state output, no match, tail clamping, control-byte stripping, and the empty `DOCKER_HOST` fallback. |
| `tests/test_alerting.py` | `send_alert` embeds and severity, the `fetch_channel` fallback, never raising on a bad channel or a send failure, and `post_report` for forum versus text channels. |
| `tests/test_nl.py` | DM handling, mention stripping, empty question, ignoring an unmentioned guild message, and always replying on failure. |
| `tests/test_bot.py` | Message chunking, slash command registration, and the Discord log handler forwarding INFO while quieting httpx. |
| `tests/test_watchlist.py` | Watch-list add/remove/list roundtrip and separator-agnostic lookup. |
| `tests/test_llm.py` | LLM client construction, plus the live endpoint check (integration). |
| `tests/test_discord_token.py` | The live Discord token check (integration). |

`tests/fixtures/sample_incident.yml` is available as fixture data.

## The evaluation notebooks

`eval/` holds eight notebooks that run against a real LLM endpoint and real backends.
They are for measuring model behavior, not for CI: nothing in `tests/` imports them.
The `dev` group installs `ipykernel`, but no notebook server, so point your own Jupyter
or editor at the project's `.venv` as the kernel.

Notebooks `01` to `07` each isolate one tool: `list_services`, `docker_status`,
`docker_logs`, `query_prometheus`, `query_prometheus_range`, `query_loki`,
`query_loki_range` (the Prometheus and Loki notebooks also bind their discovery helpers,
since a query is not answerable without knowing what metrics or labels exist). Each one
rebuilds a minimal agent loop from scratch and deliberately does not import
`agent.engine`. That is the point of the exercise: the loop is written out in the
notebook so you can see and change it, and it proves the tools work independently of the
production loop.

Each of those notebooks asks two questions. One is in scope for the bound tool. The
other is deliberately out of scope, needing evidence from a backend that is not bound,
and it measures whether the model admits the limit or hallucinates past it. Every LLM
turn's token usage is tallied and printed as a one-line transcript when the run ends, so
each call shows what it cost.

`eval/08_all_tools.ipynb` is the full agent: all 10 tools bound at once, rebuilt as a
LangGraph state machine and compiled with the shared checkpointer from `agent.memory`.
Because the checkpointer is shared, a `thread_id` in the notebook behaves exactly like a
Discord channel. It tests tool selection with nothing taken away, then a context-free
follow-up ("Why? Show me the evidence for that.") on the same thread to prove memory,
the same question on a fresh thread to prove isolation, a `history()` dump of what the
thread holds, and `forget()` to reset.

## Adding a tool

1. Write the client half as a plain `async def` in the relevant module under
   `src/agent/tools/` (or a new module for a new backend). It uses `httpx2` and returns
   whatever shape is natural: a dict, a list, a string.
2. Wrap it in a second `async def` decorated with `@tool` from `langchain_core.tools`.
   The wrapper takes only JSON-friendly arguments, clamps anything unbounded against the
   relevant setting, and returns a string truncated to 4000 characters.
3. Add it to `ALL_TOOLS` and `__all__` in `src/agent/tools/__init__.py`. That list is
   what `workflows/investigate.py` binds, so a tool not in it is invisible to the agent.
4. Keep it read-only. The guarantee that the agent cannot change anything is the tool
   surface, not the prompt: if you add a call that writes, that guarantee is gone.

The docstring is the tool description sent to the model with the schema, so it is part
of the prompt and it is what steers tool choice. Write it for the model, not for a
human reader: say when to call this tool rather than another one, name the argument
format, and state the failure modes worth avoiding. `get_loki_label_values` is the
clearest example: its description warns that Loki's labels come from Promtail and are
not Docker container names, which is what stops the model guessing a `container` label.

Errors inside a tool should come back as a string, not an exception. `docker_status`
returns `(no container matching 'x')` and `({name} matches 2 names: ...)` rather than
raising, so the model can react. The engine catches anything that does escape and feeds
it back as `(tool 'x' failed: ...)`, which keeps the run alive but wastes a step.

## Adding a workflow

A workflow is a plain `async def` that returns a `str`, with no Discord types in its
signature. That is what makes it testable without a gateway and reusable from the
digest scheduler, a slash command, and a notebook alike. Put it in
`src/agent/workflows/`.

Most workflows are a prompt plus a tool set handed to `engine.run`:

```python
from agent.engine import run as run_agent
from agent.tools import ALL_TOOLS

_TOOLS_BY_NAME = {t.name: t for t in ALL_TOOLS}


async def my_workflow(subject: str, thread_id: str | None = None) -> str:
    return await run_agent(
        f"...prompt about {subject}...",
        tools_by_name=_TOOLS_BY_NAME,
        system_prompt=_SYSTEM_PROMPT,
        budget_prompt=_BUDGET_PROMPT,
        thread_id=thread_id,
    )
```

Pass a `thread_id` for a conversation, omit it for a one-shot run against a fresh
thread. Narrow the tool set by passing a smaller dict; the engine looks up only what
you give it. `workflows/report.py` shows the cheapest variant: it is a template string
and one call into `investigate`.

## Adding a slash command

Commands are registered inside `setup_slash_commands` in `src/agent/bot/slash.py`:

```python
@bot.tree.command(name="thing", description="What it does")
@app_commands.describe(target="What the argument means")
async def slash_thing(interaction: discord.Interaction, target: str):
    await interaction.response.defer()
    text = await my_workflow(target)
    await _send_chunks(interaction, text)
```

Points to keep:

- Defer first if the work can take more than three seconds, which is anything that
  calls the LLM or a backend. Use `defer(ephemeral=True)` for a private reply.
- Send long output through `_send_chunks`, which splits at Discord's message limit.
- Keep the handler thin: it should translate the interaction into a workflow call and
  the result back into messages, nothing more.
- Errors raised out of a command are handled by the tree-level `on_app_command_error`
  at the bottom of the file, which maps cooldowns, missing permissions and check
  failures to readable ephemeral messages.
- `tests/test_bot.py::test_slash_commands_registered` asserts a list of command names
  against a fake tree; add the new name there.

Commands are synced once in `on_ready`. Set `DISCORD_GUILD_ID` while developing so the
sync is per guild and takes effect immediately instead of propagating globally.

## Conventions

- **Async throughout.** Every client, tool, workflow and handler is `async`. The one
  exception is `watchlist/repository.py`, which uses blocking `sqlite3` for short local
  writes.
- **Tools return strings, truncated explicitly.** Every tool caps its output at 4000
  characters, and every user-visible summary is capped again in `bot/summarize.py` so it
  fits one Discord message.
- **Failure is answered, not raised, at a loop boundary.** Tool exceptions become model
  input, an LLM failure becomes a fallback message, budget exhaustion becomes a summary,
  alert send failures are logged (they run inside `tasks.loop` jobs, where a raised
  exception kills the loop silently), and the DM/mention handler always replies.
- **One name-matching rule.** Every service, container and watch-list lookup goes
  through `resolve_one` in `src/agent/normalize.py`. Do not write a second matcher: an
  exact normalized match wins, a partial match that hits several candidates raises
  `AmbiguousName` with the list.
- **Deterministic numbers, generated prose.** Where a number can be computed, compute
  it and let the model write only the narrative around it. The digest is the model for
  this: the **Details** section is rendered from the events table and never paraphrased.
