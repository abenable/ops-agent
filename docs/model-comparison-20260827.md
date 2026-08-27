# Model comparison — gemma-4-31b-it vs marconi-llm (2026-08-27)

Full-suite head-to-head of the two candidate models across all eight eval
notebooks, against live backends (Docker, Prometheus, Loki all up). Purpose:
pick the production model and find which tools burn the most tokens.

- **gemma-4-31b-it** — via `google_genai`, the model in production at the time.
- **marconi-llm** — via the LiteLLM proxy (`LLM_PROVIDER=openai`,
  `LLM_MODEL=marconi-llm`), OpenAI-compatible endpoint on the LAN.

17 cases per model (two per notebook: one in-scope, one out-of-scope for the
bound tool set; `08` adds broad / same-thread follow-up / fresh-thread
follow-up). One run per case.

## Method

- Every case ran on a **fresh thread** — `run_agent_eval` suffixes a unique run
  id unless `resume=True` is passed explicitly. Earlier runs silently resumed
  persisted SQLite threads, which replayed old failures into the model's
  context and produced phantom results; this is why the same question appeared
  to answer itself with no tool calls.
- Transcripts are dumped per model under `eval/logs/<model>/`.
- A call is **invalid** when its tool result contains `is not a valid tool`.
  Calls are paired with results positionally (one call per turn in this suite).
- Token attribution per tool = the calling AI turn's total tokens + the next
  turn's input tokens (which carry the tool result), split across the calls in
  the turn.
- Suites ran with the current system prompt, which post-dates the fix for the
  tool-name hallucination incident (see "History" below).

## Per-case results

`v` = valid tool calls, `i` = invalid (hallucinated) calls, `t` = total tokens,
flags: ⌀ = empty final answer, L = run ended at the 10-call limit.

| case | gemma-4-31b-it | marconi-llm |
|---|---|---|
| 01 inscope (list services) | 1v · 1,326t · 9.5s | 1v · 1,960t · 4.0s |
| 01 outofscope (health, discovery only) | 1v/1i · 5,224t · 267s | 1v · 1,783t · 2.7s |
| 02 inscope (status) | 1v · 1,349t · 8.8s | 1v · 1,814t · 2.9s ⌀ |
| 02 outofscope (logs, status only) | 0v · 677t · 7.3s — clean refusal | 1v · 2,780t · 9.9s — status instead, no logs |
| 03 inscope (logs) | 1v · 3,108t · 9.0s | 1v · 3,800t · 4.0s |
| 03 outofscope (health, logs only) | 1v/1i · 5,113t · 19.8s | 1v · 3,836t · 4.3s — health from logs, legitimate |
| 04 inscope (instant query) | 1v · 2,125t · 12.1s | 1v · 2,494t · 2.6s |
| 04 outofscope (trend, instant only) | 7v · 10,507t · 34.3s — improvised trend from instant queries | 1v · 2,681t · 4.8s — correct "cannot trend" |
| 05 inscope (range query) | 1v · 4,820t · 8.9s | 2v · 7,741t · 4.0s |
| 05 outofscope (logs, prom only) | 0v · 748t · 6.2s — clean refusal | 0v · 1,563t · 5.3s — clean refusal |
| 06 inscope (loki errors) | 3v · 9,904t · 27.5s | 10v · 49,921t · 19.7s ⌀ |
| 06 outofscope (CPU, loki only) | 0v · 977t · 12.6s — clean refusal | 0v · 1,513t · 5.1s — clean refusal |
| 07 inscope (loki range) | 2v · 4,730t · 22.0s | 13v L · 17,139t · 34.5s — limit exit 13/10 |
| 07 outofscope (health, loki only) | 3v · 9,223t · 20.4s | 2v · 5,220t · 4.7s |
| 08 broad ("anything wrong?") | 12v L · 3,269t · 15.4s — limit exit 12/10 | 11v L · 3,695t · 3.4s — limit exit 11/10 |
| 08 follow-up, same thread | 0v · 3,010t · 25.6s — recalled context | 1v · 5,104t · 3.8s — recalled context |
| 08 follow-up, fresh thread | 0v · 1,585t · 11.3s — asked for context (correct) | 11v L · 4,102t · 6.3s — re-ran a full sweep |

## Averages

| | gemma-4-31b-it | marconi-llm |
|---|---|---|
| valid tool calls / run | 2.00 | 3.41 |
| invalid (hallucinated) calls / run | 0.12 (2 of 17 runs) | **0.00** |
| tokens / run | 3,982 | 6,891 (+73%) |
| duration / run | 30.5 s | **7.2 s** (4.3× faster) |
| runs ending at the call limit | 1 | 3 |
| empty final answers | 0 | 2 (11.8% of runs) |

## Tokens per tool

Average tokens per invocation · total spent across the suite.

| tool | gemma avg · total | marconi avg · total |
|---|---|---|
| `query_loki` | 5,814 · 11.6k | **10,484 · 73.4k** |
| `query_loki_range` | 4,821 · 14.5k | 3,289 · 26.3k |
| `get_loki_label_values` | 1,859 · 5.6k | 2,119 · 21.2k (10 calls) |
| `query_prometheus` | 2,197 · 17.6k | 3,599 · 7.2k |
| `docker_logs` | 3,676 · 7.4k | 3,634 · 7.3k |
| `query_prometheus_range` | 4,710 · 4.7k | 6,523 · 6.5k |
| `list_services` | 1,506 · 6.0k | 2,572 · 10.3k |
| `list_metric_names` | 1,932 · 1.9k | 2,380 · 4.8k |
| `docker_status` | 282 · 3.1k | 384 · 8.4k |

## Findings

**Model behaviour.**

- Hallucinated tool names: gemma did it twice even with the fixed prompt
  (`get_container_metrics` with discovery only, unbound `list_services` when
  only `docker_logs` was bound); marconi-llm never did. Gemma's residual rate
  is exactly one speculative call before it reads the error and complies.
- marconi-llm knows when a capability is missing and says so (04 outofscope is
  the clean example: "instant queries cannot generate trends" vs gemma
  improvising seven queries to fake a trend). Cost: it spends 73% more tokens
  per run, mostly by re-checking things (`05` inscope: a needless
  `list_metric_names` first; `08` fresh thread: a full 11-call sweep for a
  follow-up with no antecedent).
- Both models blow the 10-call budget on "check everything" questions by
  calling `docker_status` once per container (10 containers = 10 calls) and
  get cut off with no summary. This is a harness/prompt design gap, not a
  model gap.
- Gemma's latency is erratic: 30s average, with a 267s outlier (long thinking
  on a refusal). marconi-llm is 3-4s per run.

**Reliability.**

- marconi-llm returned `finish_reason=stop` with **empty text** twice (02
  inscope, 06 inscope) — the user gets nothing. Intermittent; suspected proxy
  or streaming quirk, not prompt-related. Until diagnosed, this is an
  adoption blocker for production.
- The limit-exit path (`ToolCallLimitMiddleware`, `exit_behavior="end"`) ends
  the run with "Tool call limit reached" as the final message — no summary of
  what was gathered. Both models suffered this; it wastes every call made.

**Tool cost.**

- The Loki family dominates spend: `query_loki` alone averaged **10.5k tokens
  per call** under marconi-llm (73k total). The tools return raw JSON with
  `stats` blocks (`bytesProcessedPerSecond`, …) that no model needs, plus
  verbose envelopes. Trimming stats and compacting the response is the single
  highest-value optimisation available.
- `get_loki_label_values` was probed 10 times by marconi-llm, half of them for
  labels that don't exist (`level`, `log_level`, `severity`, `source`). The
  tool should return the available label list when asked for an unknown label
  instead of an error, so the model stops guessing.
- `docker_status` is cheap (≤400 tokens/call) and fine to fan out.
- `list_services` results are small but sit in front of every run; no action.

## Recommendations

1. **Adopt marconi-llm** for the agent loop, conditional on fixing the
   empty-answer quirk. It is faster, never hallucinates tool names, and
   respects capability boundaries. Keep gemma as fallback.
2. Add a **retry-on-empty** rule to `ModelRetryMiddleware` (an empty final
   answer with `finish_reason=stop` should count as a retryable failure), and
   instrument the proxy to find why content comes back empty.
3. **Trim Loki tool responses**: drop `stats`, compact the JSON envelope.
   Expected saving: several thousand tokens per Loki-heavy investigation.
4. Make `get_loki_label_values` self-describing: on an unknown label, return
   the valid label names.
5. Fix the **limit-exit dead end**: either raise `run_limit` for broad sweeps
   or teach the prompt to prefer one aggregate query (`up == 0`) over
   per-container polling, so the budget buys a conclusion instead of dying
   mid-sweep.
6. Re-run the suite **3× per model** before the final call — this is a single
   snapshot, and the empty-answer quirk is intermittent by nature.

## Reproducing

```bash
cd eval
LLM_PROVIDER=google LLM_MODEL=gemma-4-31b-it python run_suite.py   # or
LLM_PROVIDER=openai LLM_MODEL=marconi-llm python run_suite.py
python analyze.py gemma-4-31b-it marconi-llm
```

`run_suite.py` / `analyze.py` live in the eval tooling; transcripts land in
`eval/logs/<model>/` (gitignored).

## History

This comparison exists because of a production incident on 2026-08-27: the
logged system prompt differed from the prompt the model actually received
(stale in-process state), and the prompt itself mandated a workflow whose tools
were not bound, driving the model to invent tool names — 11 calls in a spiral
ending at the run limit with no answer. Fixes shipped the same day: the prompt
now treats the bound tool list as authoritative and makes the discovery step
conditional (`864cf9c`), and the eval harness runs each case on a fresh thread
(`478fc66`).
