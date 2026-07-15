# 01 — Critical Bugs 🔴

Both are **confirmed reproduced**, not theoretical. Each breaks a listed deliverable.

---

## 1.1 `asyncio.run()` cannot run inside the API / bot event loop

**Files:** `src/agent/workflows/incident.py:14-16`, called from
`src/agent/api/routes.py:35` and `src/agent/bot/commands.py:30`

`run_incident_workflow()` is a **sync** function that calls `asyncio.run(...)` three times:

```python
status  = asyncio.run(get_service_status(service))
metrics = asyncio.run(get_service_metrics(service))
logs    = asyncio.run(get_recent_logs(service, lines=20))
```

Both real callers are already inside a running event loop:
- FastAPI `async def create_incident` (uvicorn loop)
- Discord `async def incident` command (discord.py loop)

`asyncio.run()` refuses to nest, so both crash. Reproduced:

```
POST /incidents/web  → 500
RuntimeError: asyncio.run() cannot be called from a running event loop
```

The CLI path (`python -m agent incident --service web`) works only because there's no
running loop — which is why tests didn't catch it (`test_workflow` is `@pytest.mark.skip`).

**Impact:** The incident workflow — the core deliverable — is broken on both of its
production entry points. Only the CLI works.

**Fix (recommended):** Make the workflow `async` and await the tools directly; call it with
`await` from the async routes/commands, and wrap once with `asyncio.run()` only in the CLI.

```python
async def run_incident_workflow(service: str) -> str:
    status  = await get_service_status(service)
    metrics = await get_service_metrics(service)
    logs    = await get_recent_logs(service, lines=20)
    ...
    # LLM: use await get_llm().ainvoke(prompt) so the sync .invoke() doesn't block the loop
```

- `routes.py`: `return {"summary": await run_incident_workflow(service)}`
- `commands.py`: `summary = await run_incident_workflow(service)`
- `cli.py `_run_incident`: `print(asyncio.run(run_incident_workflow(args.service)))`

**Secondary issue in the same spot:** even after the fix, `get_llm().invoke(prompt)` is a
**blocking** sync call inside the async loop — it stalls every other request/command for the
duration. Use `await get_llm().ainvoke(prompt)`.

**Guardrail:** un-skip `test_workflows.py` with a mocked LLM (see 05) so this path is
exercised through the async entry points, not just imported.

---

## 1.2 Docker unix-socket calls use a sync transport on an `AsyncClient`

**File:** `src/agent/tools/docker.py:15-16`

```python
transport = httpx.HTTPTransport(uds=socket_path)   # sync transport
return httpx.AsyncClient(base_url=base_url, transport=transport, ...)
```

`AsyncClient` requires an async transport (`handle_async_request`). `HTTPTransport` only
implements `handle_request`. Verified:

```
HTTPTransport has handle_async_request: False
has AsyncHTTPTransport: True   (also supports uds=)
```

**Impact:** Any Docker call over the default unix socket (`list_containers`,
`container_logs`, `restart_container`) fails at runtime. `test_docker.py` never hit it — it
only tests the "no socket → return []" short-circuit and the TCP availability flag.

**Fix:** one word.

```python
transport = httpx.AsyncHTTPTransport(uds=socket_path)
```

**Guardrail:** add a test that mocks `AsyncClient.get` and asserts `list_containers` parses a
response, so the transport path is actually constructed/awaited.
