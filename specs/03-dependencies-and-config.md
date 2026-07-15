# 03 — Dependencies & Config 🟠

---

## 3.1 `httpx2` — obscure, non-standard HTTP dependency

**Files:** `pyproject.toml:16`, and every HTTP call site
(`tools/health.py`, `tools/docker.py`, `tools/sources/*.py`, `tests/test_discord_token.py`)

The project imports `import httpx2 as httpx` everywhere. `httpx2` (v2.7.0) was published to
PyPI on **2026-07-14 — one day before this review**, and pulls its own `httpcore2` fork.
The industry-standard client is `httpx`, which is **already installed** in this venv
(`httpx 0.28.1`, as a transitive dep).

I read the `httpx2` source: it's a clean copy of httpx's internals with no obvious malicious
payload (no `eval/exec/subprocess`, no network exfil, no obfuscation). So this is a
**dependency-hygiene** flag, not a confirmed compromise. But taking a brand-new,
single-maintainer package as your HTTP foundation — when the standard one is right there — is
avoidable supply-chain risk, and the `as httpx` aliasing hides that you're not on the real
thing.

**Fix:** switch to standard `httpx`.
- `pyproject.toml`: replace `"httpx2>=2.7.0"` with `"httpx>=0.28"`.
- Replace `import httpx2 as httpx` → `import httpx` in the 4 source files + 1 test.
- `uv lock && uv sync`. The API is identical (`AsyncClient`, `AsyncHTTPTransport`, `get`),
  so no other code changes are needed. (Combine with the 1.2 transport fix.)

---

## 3.2 `.env.example` API-key variable doesn't match what settings reads

**Files:** `.env.example:9` vs `src/agent/config/settings.py:27-30`

`.env.example` documents `LLM_API_KEY=sk-optional`, but `Settings.llm_api_key` reads from
`validation_alias="OPENAI_API_KEY"`. A user who copies `.env.example` verbatim sets
`LLM_API_KEY`, which is **ignored** — the LLM key silently stays empty.

**Fix:** make them agree. Either rename the env var to `OPENAI_API_KEY` in `.env.example`
(matches the real `.env` and LangChain's own convention), or change the alias to `LLM_API_KEY`.
Recommend standardizing on `LLM_API_KEY` since the field is named `llm_api_key` and the
project bills itself as provider-agnostic/self-hosted.

---

## 3.3 Settings defaults contradict the "self-hosted LLM" story

**File:** `src/agent/config/settings.py:25-26`

```python
llm_base_url = "https://litellm.byte10x.dev/v1"
llm_model    = "Kimi-K2.7-Code"
```

The default points at a specific **remote** hosted gateway, while `.env.example` and the docs
describe a self-hosted local endpoint (`http://localhost:11434/v1`, `mistral`). For a
deliverable titled "self-hosted LLM integration," the baked-in default should be the local
one (or empty), so a fresh checkout doesn't silently call out to a third-party service.

**Fix:** default `llm_base_url`/`llm_model` to the local values (or `""`) and keep the hosted
endpoint only in your private `.env`.

---

## 3.4 `langgraph` (and arguably `langchain`) are declared but unused

**File:** `pyproject.toml:8-10`

`langgraph>=1.2.9` is a dependency but nothing imports it — the workflow is a fixed
sequential pipeline, not a graph. `langchain` is only pulled in transitively via
`langchain-openai` (the only thing actually used is `ChatOpenAI`).

**Fix (ponytail):** drop `langgraph` and the top-level `langchain` from `pyproject.toml`
until a workflow actually uses them. Keep `langchain-openai`. Smaller install, honest
dependency list. Re-add `langgraph` when/if you build the real state-machine workflow
(the README already frames this as future work).
