# Testing

```bash
uv run pytest                  # full suite — no external services needed
uv run pytest -m integration   # only the live checks (real LLM / Discord token)
```

The default run is 56 offline tests; the three integration-marked ones are
excluded by `addopts` and run only via `pytest -m integration`.
Nothing in the default run needs Docker, Discord, Prometheus, Loki, or an LLM —
those boundaries are mocked.

## What is covered

| File | Tests | Covers |
| --- | --- | --- |
| `test_investigate.py` | 7 | The LangGraph loop: tool execution, direct answers, tool errors fed back to the model, the `MAX_TOOL_STEPS` cap + final-summary fallback, LLM outage handling, the `/report` incident template, per-`thread_id` conversation state |
| `test_monitor.py` | 13 | The alert loop: endpoint parsing, endpoint probing and down/recovery alerts, running→down and down→running transitions, no false alert on the first poll after a restart, watch-list/filter scoping, state pruning, the end-to-end demo scenario |
| `test_services.py` | 7 | The minimal clients: bearer-token headers for Prometheus/Loki, invalid-label rejection, Loki's range-endpoint regression, Docker log-stream demuxing |
| `test_docker_tools.py` | 6 | The Docker LangChain tools: status/logs output, tail cap, control-byte stripping, empty `DOCKER_HOST` fallback |
| `test_summarize.py` | 12 | LLM output cleanup: Discord markdown normalization (headings, tables→bullets), length caps, raw-output fallback when the LLM fails |
| `test_alerting.py` | 4 | Alert embeds, channel-cache miss → API fetch fallback, Discord errors never raising into the monitor loop |
| `test_normalize.py` | 7 | `resolve_one`: separator-agnostic matching, exact-name precedence, and ambiguous-partial rejection for containers and the watch list |
| `test_memory.py` | 2 | Conversation memory: thread history/forget roundtrip, thread config |
| `test_digest.py` | 9 | Daily/weekly bodies, outage pairing and downtime totals, weekday gating, the flapping narrative, unset status channel |
| `test_watchlist.py` | 2 | Watch-list SQLite roundtrip and fuzzy removal |
| `test_bot.py` | 3 | Message chunking, slash-command registration, Discord log forwarding |
| `test_llm.py` | 2 | Client construction + a live ping (integration-marked) |
| `test_discord_token.py` | 1 | Token sanity check (integration-marked) |

## Conventions

- Async code is tested with `asyncio.run(...)` — no pytest-asyncio dependency.
- Discord objects are `MagicMock`/`AsyncMock`; HTTP clients are replaced at the
  `httpx2.AsyncClient` boundary; the LLM is replaced by a fake that plays back
  canned `AIMessage`s (see `test_investigate.py`).
- The demo incident scenario (stop a container → alert → report → recovery) is
  regression-covered by an integration-marked test in `test_monitor.py`; see
  [demo.md](demo.md).
