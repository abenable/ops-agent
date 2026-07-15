# 05 — Tests & Minor Cleanups 🟡

Current state: `uv run pytest -q` → **15 passed, 1 skipped** in ~9s. Good baseline. The gaps
below are what the passing suite doesn't actually cover, plus small correctness nits.

---

## 5.1 The two critical bugs (01) have no failing test — that's why they shipped

- `test_workflows.py` is `@pytest.mark.skip("requires a running LLM")`, so the incident path
  is never exercised → 1.1 went undetected.
- `test_docker.py` only tests the "no socket → []" and TCP-flag branches → 1.2 went
  undetected.

**Fix:** mock the LLM and the HTTP client so these run in CI without external services:
- Un-skip `test_incident_workflow`: monkeypatch `agent.workflows.incident.get_llm` to return
  a fake with `.ainvoke()` returning a stub message; call the (now async) workflow with
  `asyncio.run`; assert a summary string and that an incident row was stored. Better: also
  hit `POST /incidents/{service}` via `TestClient` and assert 200 — that's the regression
  test for 1.1.
- Add a `list_containers` test that patches `AsyncClient.get` to return a fake JSON response,
  proving the transport path constructs and awaits (regression test for 1.2).

---

## 5.2 `test_ssh` is non-hermetic and slow

**File:** `tests/test_ssh.py:8`

It shells out to a **real** `ssh 127.0.0.1`. On a host without sshd it waits out
`ConnectTimeout=5`, and results depend on the environment. It only checks dict shape, so a
fully mocked `asyncio.create_subprocess_exec` gives the same assertion without the network
dependency or the 5s stall.

**Fix:** patch `asyncio.create_subprocess_exec` to return a fake proc with canned
stdout/stderr/returncode; assert the returned dict shape and that the arg list contains the
expected `BatchMode=yes` / `user@host` / command.

---

## 5.3 No test for the reporting workflow or the `!incident`/API create→report loop

`run_report_workflow` (found + not-found branches) and the end-to-end create→report flow are
untested. Cheap to add once 4.4 (surface incident id) lands.

---

## 5.4 Small correctness nits

- **`docker.py:30` — `_docker_available()` for non-unix, non-tcp hosts:** returns
  `os.path.exists(docker_host[7:])`, which mangles anything that isn't `unix://...`. Guard
  explicitly for the `unix://` prefix and return `False` otherwise.
- **`repository.py:9` — DB path is CWD-relative** (`sqlite:///data/agent.db` →
  `data/agent.db`). Running the CLI/bot from a different directory creates a *different*
  database than the one the API/tests expect. Resolve it against the project root (or an
  absolute `DATABASE_URL`) so all entry points share one DB.
- **`repository.py` — `init_db()` runs on every read/write.** Harmless (idempotent) but
  wasteful; call it once at startup instead of inside every function.
- **`workflows/incident.py:29` — LLM-failure fallback dumps the full prompt** (including raw
  logs/metrics) into the "summary" that then gets stored and, if you wire 4.1, posted to
  Discord. Fine for a lab; consider a shorter fallback message so failures don't leak large
  context blobs into the alert channel.

---

## 5.5 Nice-to-haves for the demo (not blockers)

- Add a `ruff`/`ruff format` config + a `make check` (or `uv run` script) so the grader can
  one-command lint/test. There's a lone `# noqa: T201` in `bot/client.py` implying a linter
  was expected but none is configured.
- The architecture doc shows LLM tool-use, but the LLM never actually calls tools — it just
  summarizes pre-fetched text. If a true "agent" (LLM decides which tool to call) is expected
  for the demo, that's a design gap to call out explicitly rather than imply. Ponytail take:
  the fixed pipeline is fine for the MVP — just make the docs match what it does.
