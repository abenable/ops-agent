# Model size comparison and its effect on the agent

This document records the measured effect of LLM size on the Marconi agent's
behaviour, based on testing during the implementation phase. The agent drives a
bounded, read-only tool-calling loop; the loop itself is fixed, so differences
in outcome between models are differences in **instruction following and tool
selection**, not in the mechanism.

## TL;DR

- Model size is the dominant factor in whether the agent **calls a tool** for a
  vague question or **answers in prose** (often hallucinated).
- A 1.5B-parameter instruct model can emit tool calls when the user message
  *explicitly* asks for one, but does not reliably choose to call a tool for a
  vague question, even when the system prompt tells it to.
- A larger model (DeepSeek v4-pro) calls the right tool for the same vague
  question on the first try, grounds its answer in the tool result, and formats
  the output as instructed.
- Switching to a hosted API trades the self-hosted/compliance design principle
  for capability. That tradeoff is a deliberate decision, not a free win.

## Models compared

| Provider (`LLM_PROVIDER`) | Model | Params | Hosting | Tested? |
| --- | --- | --- | --- | --- |
| `vllm` | `Qwen/Qwen2.5-1.5B-Instruct` | ~1.5B | self-hosted (vLLM on `alien`) | yes |
| `""` (legacy) | `deepseek-v4-pro` | large (hosted) | DeepSeek official API | yes |
| `""` (legacy) | `Kimi-K2.7-Code` via LiteLLM gateway | large (hosted) | LiteLLM gateway | configured, not measured |
| `""` (legacy) | `deepseek-v4-flash` | smaller (hosted) | DeepSeek official API | not measured |

All four speak the OpenAI-compatible `/v1/chat/completions` protocol with
tool-calling, so they are interchangeable by changing `LLM_PROVIDER` and the
`*_BASE_URL` / `*_MODEL` / `LLM_API_KEY` env vars. No code change is required.

## Measured behaviour: same prompt, same tool, same vague question

Both models were sent an identical request through their OpenAI-compatible API:

- **System prompt:** the agent's investigator persona ("Start by calling
  `list_services` to learn the real container and endpoint names…").
- **User message:** `what containers are up` (vague; the exact phrasing that
  triggered the original bug in a Discord DM).
- **Tools:** `list_services` (the discovery tool).
- **`tool_choice`:** `auto` (the agent decides).

| Model | `finish_reason` | Tool call? | Response |
| --- | --- | --- | --- |
| `Qwen/Qwen2.5-1.5B-Instruct` | `stop` | **no** | Narrated intent instead of acting: *"To determine which containers are running… I will use the `list_services` tool…"* and then hallucinated a reference to **Oracle Cloud Infrastructure (OCI)** — confusing the "Oracle" bot persona with the cloud company. |
| `deepseek-v4-pro` | `tool_calls` | **yes** | Called `list_services({})` immediately. |

When the same 1.5B model is given a user message that *explicitly* says "List the
running containers using `list_services`", it does emit the tool call and
returns the correct, grounded list. So the failure is **tool selection on vague
input**, not tool-calling capability. The larger model makes the right
selection regardless of how the question is phrased.

End-to-end through the agent's HTTP API (`POST /api/ask/stream`), DeepSeek v4-pro
called `list_services`, received the nine real containers, and returned a
grounded, structured answer (a table of container names plus a one-line
summary), with the startup tool-support probe passing on the first attempt and
no retries.

## Other observed effects of model size

- **Prompt-format compliance.** The 1.5B model emits Markdown `####` headings
  in command summaries despite being told to use `**bold**` (Discord does not
  render `#` headings). This required a fence-aware post-processor
  (`_discordify` in `agent.bot.summarize`) to normalise headings to bold. The
  larger model follows the formatting instruction directly.
- **Startup probe reliability.** The `llm_supports_tool_calls` probe is a
  single best-effort call at startup. A small model that answers the probe in
  prose (rather than calling the tool) produces a false-negative warning even
  though it is technically capable of tool calls. The larger model passes the
  probe cleanly on the first attempt. The warning gates only a log line; it
  does not disable tool-calling at runtime, so a false negative is not fatal.
- **Connection retries.** Against a cold local vLLM the OpenAI client
  occasionally retries `/chat/completions` in the first second after
  `on_ready`; against the hosted DeepSeek endpoint the first request succeeds
  with no retries.

## Tradeoffs

- **Capability vs compliance.** The agent's stated design principle is
  *self-hosted, for organisations that cannot send operational telemetry to a
  third-party hosted LLM for compliance reasons* (see the architecture report).
  DeepSeek's official API sends container names, log/metric queries, and
  summaries to a third party. Self-hosted vLLM (Qwen) keeps all data on-prem.
  Choosing a hosted model is a compliance regression that must be a deliberate
  decision for the deployment environment.
- **Capability vs cost.** The hosted DeepSeek API is pay-per-token with
  per-request latency dominated by the internet round trip. Self-hosted vLLM
  has no per-request cost but requires a GPU and is bounded by local VRAM (which
  is what forces the 1.5B model in the first place).
- **Latency.** A local vLLM on the same host network is a sub-millisecond
  hop; a hosted API adds wide-area latency. For an interactive Discord bot
  this is usually acceptable, but it compounds across the bounded tool-calling
  loop (up to `MAX_TOOL_STEPS` sequential LLM calls per investigation).
- **Determinism.** If a deployment must stay self-hosted and cannot run a
  larger model, the alternative to "bigger model" is a small intent-classifier
  that maps question types to forced tool calls (e.g. *containers?* →
  `list_services`). That is more code and more brittle than a 7B+ model and is
  only worth it when the GPU budget is fixed.

## Recommendation

1. **Use the largest model the deployment's constraints allow.** Tool
   selection and instruction following scale with parameter count; the
   mechanism does not.
2. **If self-hosting is required**, step up within the vLLM stack to a 7B-14B
   instruct model with tool-calling (e.g. `Qwen/Qwen2.5-7B-Instruct` or 14B) on
   the same vLLM server — one `VLLM_MODEL` change. This preserves the compliance
   principle and fixes the tool-selection failure.
3. **If a hosted API is acceptable**, `deepseek-v4-pro` works correctly out of
   the box with `LLM_PROVIDER=""`, `LLM_BASE_URL=https://api.deepseek.com/v1`,
   and an API key. The LiteLLM/Kimi gateway is an equivalent hosted option.
4. **Keep the mechanism as-is.** The bounded ReAct loop, `bind_tools`, the
   `ToolMessage` feedback, and the output clamping are correct and standard.
   Rebuilding them does not fix instruction-following; a bigger model does.

## How to switch

The provider is selected by `LLM_PROVIDER` in `.env` (see `docs/setup.md`).
The three named presets are `""` (legacy / any OpenAI-compatible endpoint),
`ollama`, and `vllm`; `set_llm_provider` flips it at runtime and a Discord
button (`LLMProviderView`) exposes the switch in chat.

```env
# Self-hosted, larger (recommended when compliance requires on-prem):
LLM_PROVIDER=vllm
VLLM_BASE_URL=http://localhost:8000/v1
VLLM_MODEL=Qwen/Qwen2.5-7B-Instruct      # step up from 1.5B

# Hosted, capable (when sending data off-prem is acceptable):
LLM_PROVIDER=
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-v4-pro
LLM_API_KEY=sk-...
```
