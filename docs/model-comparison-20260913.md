# Model comparison — gemma-4-31b-it vs marconi-llm (2026-09-13)

Full-suite head-to-head of the two candidate models across all eight eval
notebooks, against live backends (Docker, Prometheus, Loki all up on
marconi-02). Purpose: pick the production model on evidence that survives more
than one sample.

- **gemma-4-31b-it** — via `google_genai`, Google's hosted endpoint. The model
  in production at the time of writing.
- **marconi-llm** — via the LiteLLM proxy (`LLM_PROVIDER=openai`,
  `LLM_MODEL=marconi-llm`), OpenAI-compatible endpoint on the LAN.

17 cases per model, **2 runs each = 34 runs per model, 68 total**. Cases are
two per notebook (one in-scope, one out-of-scope for the bound tool set), plus
`08`'s broad / same-thread follow-up / fresh-thread follow-up.

This supersedes `model-comparison-20260827.md`, which ran one sample per case.
Several conclusions here are only visible with a second run.

## Method

- Every case ran on a **fresh thread** — `run_agent_eval` suffixes a unique run
  id unless `resume=True`. Each repetition additionally gets its own thread, so
  `08`'s `resume=True` case cannot replay repetition 1 into repetition 2.
- Transcripts dumped per model under `eval/logs/<model>/`. The 38 transcripts
  from the 2026-08-27 round were archived off the path first
  (`/tmp/eval-logs-archive-20260827/` on marconi-02) so they could not be
  averaged into these figures.
- A call is **invalid** when its tool result contains `is not a valid tool`.
  Calls are matched to results **by `tool_call_id`**, not positionally, so
  parallel tool calls are attributed correctly.
- Token attribution per tool = the calling AI turn's total tokens + the next
  turn's input tokens (which carry the tool result), split across the calls in
  that turn.
- Budget is production's: `ToolCallLimitMiddleware(run_limit=20,
  exit_behavior="end")`. **Neither model reached it** — max observed was 16
  (gemma) and 12 (marconi-llm).
- `errored_runs` counts runs that raised, plus runs whose answer is
  `ModelRetryMiddleware`'s "Model call failed after N attempts". **Both models
  scored 0/34**, so no endpoint failure is hiding inside these averages.

## Headline

| metric | gemma-4-31b-it | marconi-llm |
|---|---|---|
| runs | 34 | 34 |
| valid tool calls / run | 2.03 | **3.56** |
| invalid (hallucinated) calls / run | 0.09 | **0.00** |
| runs containing a hallucinated call | **3/34** (8.8%) | **0/34** |
| runs with a degenerate answer | **0/34** | **2/34** (5.9%) |
| errored runs | 0/34 | 0/34 |
| empty answers | 0 | 0 |
| tokens / run | **6,183** | 10,439 (+69%) |
| total tokens across suite | **210,234** | 354,931 |
| wall clock / run | 29.1s | **13.6s** (2.1× faster) |
| seconds per 1k tokens | 4.71 | **1.30** (3.6× faster) |
| max tool calls in one run | 16 | 12 |
| runs hitting the 20-call budget | 0 | 0 |

## Per-case summary (mean of 2 runs)

`v` = valid tool calls, `i` = invalid (hallucinated) calls, `t` = total tokens.

| case | gemma-4-31b-it | marconi-llm |
|---|---|---|
| `01_list_services:live-inscope` | 1.0v/0.0i · 1,659t · 19.1s | 1.0v/0.0i · 1,912t · 5.3s |
| `01_list_services:live-outofscope` | 1.0v/0.5i · 3,902t · 57.9s ⚠ `get_container_status` | 1.0v/0.0i · 1,986t · 7.0s |
| `02_docker_status:live-inscope` | 1.0v/0.0i · 1,416t · 10.1s | 1.0v/0.0i · 1,766t · 3.6s |
| `02_docker_status:live-outofscope` | 0.5v/0.0i · 1,768t · 16.7s | 1.0v/0.0i · 1,846t · 4.9s |
| `03_docker_logs:live-inscope` | 1.0v/0.0i · 3,163t · 24.7s | 1.0v/0.0i · 3,666t · 5.0s |
| `03_docker_logs:live-outofscope` | 1.0v/1.0i · 4,934t · 19.1s ⚠ `list_services` | 1.0v/0.0i · 3,989t · 5.1s |
| `04_query_prometheus:live-inscope` | 1.0v/0.0i · 2,032t · 11.2s | 1.0v/0.0i · 2,512t · 3.7s |
| `04_query_prometheus:live-outofscope` | 5.0v/0.0i · 12,534t · 39.0s | 12.0v/0.0i · 17,048t · 28.7s |
| `05_query_prometheus_range:live-inscope` | 1.0v/0.0i · 4,826t · 14.0s | 3.0v/0.0i · 18,672t · 8.6s |
| `05_query_prometheus_range:live-outofscope` | 0.0v/0.0i · 783t · 6.6s | 7.5v/0.0i · 26,504t · 23.8s |
| `06_query_loki:live-inscope` | 4.0v/0.0i · 14,054t · 48.3s | 11.0v/0.0i · 49,904t · 54.0s |
| `06_query_loki:live-outofscope` | 0.0v/0.0i · 974t · 12.5s | 2.5v/0.0i · 4,842t · 11.3s |
| `07_query_loki_range:live-inscope` | 5.0v/0.0i · 24,858t · 56.4s | 5.5v/0.0i · 17,474t · 20.6s |
| `07_query_loki_range:live-outofscope` | 2.5v/0.0i · 7,072t · 65.3s | 4.0v/0.0i · 11,245t · 13.6s |
| `08_all_tools:broad` | 10.5v/0.0i · 15,331t · 39.7s | 4.5v/0.0i · 6,949t · 9.4s |
| `08_all_tools:followup-fresh-thread` | 0.0v/0.0i · 1,450t · 25.4s | 0.0v/0.0i · 1,826t · 18.7s |
| `08_all_tools:followup-same-thread` | 0.0v/0.0i · 4,359t · 29.4s | 3.5v/0.0i · 5,324t · 7.9s |

## Every run (all 68)

| model | case | run | turns | tools | valid | invalid | in | out | total | duration | ans chars | LC | RA |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gemma-4-31b-it | `01_list_services:live-inscope` | 1 | 4 | 1 | 1 | 0 | 1,109 | 907 | 2,016 | 28.4s | 461 | y | y |
| gemma-4-31b-it | `01_list_services:live-inscope` | 2 | 4 | 1 | 1 | 0 | 1,055 | 247 | 1,302 | 9.9s | 475 | y | y |
| gemma-4-31b-it | `01_list_services:live-outofscope` | 1 | 4 | 1 | 1 | 0 | 1,611 | 1,213 | 2,824 | 67.9s | 300 | y | y |
| gemma-4-31b-it | `01_list_services:live-outofscope` | 2 | 6 | 2 | 1 | 1 | 3,404 | 1,577 | 4,981 | 47.8s | 314 | y | y |
| gemma-4-31b-it | `02_docker_status:live-inscope` | 1 | 4 | 1 | 1 | 0 | 1,157 | 302 | 1,459 | 11.1s | 160 | y | y |
| gemma-4-31b-it | `02_docker_status:live-inscope` | 2 | 4 | 1 | 1 | 0 | 1,137 | 237 | 1,374 | 9.1s | 211 | y | y |
| gemma-4-31b-it | `02_docker_status:live-outofscope` | 1 | 2 | 0 | 0 | 0 | 476 | 395 | 871 | 12.3s | 110 | — | — |
| gemma-4-31b-it | `02_docker_status:live-outofscope` | 2 | 4 | 1 | 1 | 0 | 1,991 | 675 | 2,666 | 21.2s | 260 | y | y |
| gemma-4-31b-it | `03_docker_logs:live-inscope` | 1 | 4 | 1 | 1 | 0 | 2,930 | 195 | 3,125 | 7.9s | 198 | y | y |
| gemma-4-31b-it | `03_docker_logs:live-inscope` | 2 | 4 | 1 | 1 | 0 | 2,938 | 263 | 3,201 | 41.5s | 192 | y | y |
| gemma-4-31b-it | `03_docker_logs:live-outofscope` | 1 | 6 | 2 | 1 | 1 | 4,412 | 538 | 4,950 | 19.3s | 207 | y | y |
| gemma-4-31b-it | `03_docker_logs:live-outofscope` | 2 | 6 | 2 | 1 | 1 | 4,406 | 513 | 4,919 | 18.9s | 205 | y | y |
| gemma-4-31b-it | `04_query_prometheus:live-inscope` | 1 | 4 | 1 | 1 | 0 | 1,719 | 294 | 2,013 | 11.3s | 306 | y | y |
| gemma-4-31b-it | `04_query_prometheus:live-inscope` | 2 | 4 | 1 | 1 | 0 | 1,763 | 287 | 2,050 | 11.0s | 314 | y | y |
| gemma-4-31b-it | `04_query_prometheus:live-outofscope` | 1 | 10 | 4 | 4 | 0 | 8,320 | 688 | 9,008 | 27.7s | 282 | y | y |
| gemma-4-31b-it | `04_query_prometheus:live-outofscope` | 2 | 12 | 6 | 6 | 0 | 14,499 | 1,562 | 16,061 | 50.3s | 564 | y | y |
| gemma-4-31b-it | `05_query_prometheus_range:live-inscope` | 1 | 4 | 1 | 1 | 0 | 4,584 | 267 | 4,851 | 10.0s | 250 | y | y |
| gemma-4-31b-it | `05_query_prometheus_range:live-inscope` | 2 | 4 | 1 | 1 | 0 | 4,574 | 227 | 4,801 | 18.1s | 256 | y | y |
| gemma-4-31b-it | `05_query_prometheus_range:live-outofscope` | 1 | 2 | 0 | 0 | 0 | 610 | 151 | 761 | 6.0s | 65 | — | — |
| gemma-4-31b-it | `05_query_prometheus_range:live-outofscope` | 2 | 2 | 0 | 0 | 0 | 610 | 195 | 805 | 7.2s | 74 | — | — |
| gemma-4-31b-it | `06_query_loki:live-inscope` | 1 | 11 | 5 | 5 | 0 | 17,290 | 1,015 | 18,305 | 71.4s | 353 | y | y |
| gemma-4-31b-it | `06_query_loki:live-inscope` | 2 | 8 | 3 | 3 | 0 | 9,086 | 718 | 9,804 | 25.3s | 323 | y | y |
| gemma-4-31b-it | `06_query_loki:live-outofscope` | 1 | 2 | 0 | 0 | 0 | 591 | 419 | 1,010 | 13.7s | 275 | y | y |
| gemma-4-31b-it | `06_query_loki:live-outofscope` | 2 | 2 | 0 | 0 | 0 | 591 | 347 | 938 | 11.3s | 252 | y | y |
| gemma-4-31b-it | `07_query_loki_range:live-inscope` | 1 | 14 | 6 | 6 | 0 | 31,990 | 1,300 | 33,290 | 83.3s | 200 | y | y |
| gemma-4-31b-it | `07_query_loki_range:live-inscope` | 2 | 10 | 4 | 4 | 0 | 15,653 | 772 | 16,425 | 29.4s | 212 | y | y |
| gemma-4-31b-it | `07_query_loki_range:live-outofscope` | 1 | 8 | 3 | 3 | 0 | 8,661 | 561 | 9,222 | 75.5s | 332 | y | y |
| gemma-4-31b-it | `07_query_loki_range:live-outofscope` | 2 | 6 | 2 | 2 | 0 | 4,396 | 525 | 4,921 | 55.2s | 351 | y | y |
| gemma-4-31b-it | `08_all_tools:broad` | 1 | 24 | 16 | 16 | 0 | 18,844 | 993 | 19,837 | 55.4s | 286 | y | y |
| gemma-4-31b-it | `08_all_tools:broad` | 2 | 10 | 5 | 5 | 0 | 10,165 | 660 | 10,825 | 24.0s | 283 | y | y |
| gemma-4-31b-it | `08_all_tools:followup-fresh-thread` | 1 | 2 | 0 | 0 | 0 | 1,221 | 247 | 1,468 | 43.7s | 99 | — | — |
| gemma-4-31b-it | `08_all_tools:followup-fresh-thread` | 2 | 2 | 0 | 0 | 0 | 1,221 | 212 | 1,433 | 7.1s | 124 | — | — |
| gemma-4-31b-it | `08_all_tools:followup-same-thread` | 1 | 2 | 0 | 0 | 0 | 4,560 | 444 | 5,004 | 13.5s | 659 | y | y |
| gemma-4-31b-it | `08_all_tools:followup-same-thread` | 2 | 2 | 0 | 0 | 0 | 3,432 | 282 | 3,714 | 45.3s | 461 | y | y |
| marconi-llm | `01_list_services:live-inscope` | 1 | 4 | 1 | 1 | 0 | 1,533 | 412 | 1,945 | 5.7s | 642 | y | y |
| marconi-llm | `01_list_services:live-inscope` | 2 | 4 | 1 | 1 | 0 | 1,533 | 347 | 1,880 | 4.9s | 542 | y | y |
| marconi-llm | `01_list_services:live-outofscope` | 1 | 4 | 1 | 1 | 0 | 1,529 | 405 | 1,934 | 6.2s | 483 | y | y |
| marconi-llm | `01_list_services:live-outofscope` | 2 | 4 | 1 | 1 | 0 | 1,529 | 508 | 2,037 | 7.8s | 539 | y | y |
| marconi-llm | `02_docker_status:live-inscope` | 1 | 4 | 1 | 1 | 0 | 1,534 | 191 | 1,725 | 3.1s | 236 | y | y |
| marconi-llm | `02_docker_status:live-inscope` | 2 | 4 | 1 | 1 | 0 | 1,534 | 273 | 1,807 | 4.0s | 272 | y | y |
| marconi-llm | `02_docker_status:live-outofscope` | 1 | 4 | 1 | 1 | 0 | 1,532 | 260 | 1,792 | 4.0s | 422 | y | y |
| marconi-llm | `02_docker_status:live-outofscope` | 2 | 4 | 1 | 1 | 0 | 1,532 | 368 | 1,900 | 5.8s | 462 | y | y |
| marconi-llm | `03_docker_logs:live-inscope` | 1 | 4 | 1 | 1 | 0 | 3,395 | 232 | 3,627 | 4.4s | 466 | y | y |
| marconi-llm | `03_docker_logs:live-inscope` | 2 | 4 | 1 | 1 | 0 | 3,395 | 311 | 3,706 | 5.6s | 505 | y | y |
| marconi-llm | `03_docker_logs:live-outofscope` | 1 | 4 | 1 | 1 | 0 | 3,379 | 272 | 3,651 | 5.1s | 497 | y | y |
| marconi-llm | `03_docker_logs:live-outofscope` | 2 | 4 | 1 | 1 | 0 | 4,064 | 263 | 4,327 | 5.0s | 358 | y | y |
| marconi-llm | `04_query_prometheus:live-inscope` | 1 | 4 | 1 | 1 | 0 | 2,260 | 284 | 2,544 | 4.1s | 512 | y | y |
| marconi-llm | `04_query_prometheus:live-inscope` | 2 | 4 | 1 | 1 | 0 | 2,260 | 221 | 2,481 | 3.4s | 414 | y | y |
| marconi-llm | `04_query_prometheus:live-outofscope` | 1 | 20 | 12 | 12 | 0 | 14,789 | 1,702 | 16,491 | 28.9s | 519 | y | y |
| marconi-llm | `04_query_prometheus:live-outofscope` | 2 | 19 | 12 | 12 | 0 | 15,825 | 1,781 | 17,606 | 28.5s | 799 | y | y |
| marconi-llm | `05_query_prometheus_range:live-inscope` | 1 | 12 | 5 | 5 | 0 | 34,058 | 659 | 34,717 | 15.7s | 387 | y | y |
| marconi-llm | `05_query_prometheus_range:live-inscope` | 2 | 4 | 1 | 1 | 0 | 2,540 | 87 | 2,627 | 1.6s | 41 | — | — |
| marconi-llm | `05_query_prometheus_range:live-outofscope` | 1 | 10 | 5 | 5 | 0 | 11,940 | 824 | 12,764 | 15.6s | 684 | y | y |
| marconi-llm | `05_query_prometheus_range:live-outofscope` | 2 | 17 | 10 | 10 | 0 | 38,499 | 1,744 | 40,243 | 32.0s | 906 | y | y |
| marconi-llm | `06_query_loki:live-inscope` | 1 | 19 | 10 | 10 | 0 | 35,752 | 1,812 | 37,564 | 35.7s | 1152 | y | y |
| marconi-llm | `06_query_loki:live-inscope` | 2 | 22 | 12 | 12 | 0 | 58,881 | 3,362 | 62,243 | 72.3s | 1088 | y | y |
| marconi-llm | `06_query_loki:live-outofscope` | 1 | 6 | 2 | 2 | 0 | 4,135 | 601 | 4,736 | 10.2s | 503 | y | y |
| marconi-llm | `06_query_loki:live-outofscope` | 2 | 7 | 3 | 3 | 0 | 4,210 | 737 | 4,947 | 12.4s | 618 | y | y |
| marconi-llm | `07_query_loki_range:live-inscope` | 1 | 15 | 7 | 7 | 0 | 24,749 | 1,298 | 26,047 | 24.8s | 793 | y | y |
| marconi-llm | `07_query_loki_range:live-inscope` | 2 | 9 | 4 | 4 | 0 | 7,972 | 930 | 8,902 | 16.4s | 644 | y | y |
| marconi-llm | `07_query_loki_range:live-outofscope` | 1 | 8 | 3 | 3 | 0 | 10,519 | 588 | 11,107 | 11.3s | 608 | y | y |
| marconi-llm | `07_query_loki_range:live-outofscope` | 2 | 10 | 5 | 5 | 0 | 10,485 | 898 | 11,383 | 15.8s | 659 | y | y |
| marconi-llm | `08_all_tools:broad` | 1 | 15 | 9 | 9 | 0 | 11,286 | 736 | 12,022 | 14.4s | 375 | y | y |
| marconi-llm | `08_all_tools:broad` | 2 | 2 | 0 | 0 | 0 | 1,621 | 255 | 1,876 | 4.4s | 127 | — | — |
| marconi-llm | `08_all_tools:followup-fresh-thread` | 1 | 2 | 0 | 0 | 0 | 1,621 | 206 | 1,827 | 3.7s | 353 | — | — |
| marconi-llm | `08_all_tools:followup-fresh-thread` | 2 | 2 | 0 | 0 | 0 | 1,621 | 205 | 1,826 | 33.7s | 226 | — | — |
| marconi-llm | `08_all_tools:followup-same-thread` | 1 | 10 | 7 | 7 | 0 | 7,922 | 599 | 8,521 | 9.2s | 995 | y | y |
| marconi-llm | `08_all_tools:followup-same-thread` | 2 | 2 | 0 | 0 | 0 | 1,670 | 456 | 2,126 | 6.6s | 622 | — | — |

## Tokens per tool

| model | tool | invocations | avg tokens | total tokens |
|---|---|---|---|---|
| gemma-4-31b-it | `query_loki_range` | 14 | 7,318 | 102,456 |
| gemma-4-31b-it | `query_prometheus` | 12 | 3,383 | 40,592 |
| gemma-4-31b-it | `query_loki` | 6 | 6,586 | 39,516 |
| gemma-4-31b-it | `get_loki_label_values` | 8 | 3,063 | 24,503 |
| gemma-4-31b-it | `docker_status` | 15 | 1,448 | 21,716 |
| gemma-4-31b-it | `docker_logs` | 4 | 3,608 | 14,433 |
| gemma-4-31b-it | `list_services` | 8 | 1,484 | 11,872 |
| gemma-4-31b-it | `query_prometheus_range` | 2 | 4,666 | 9,333 |
| gemma-4-31b-it | `list_metric_names` | 2 | 1,923 | 3,846 |
| gemma-4-31b-it | `get_container_status` | 1 | 3,402 | 3,402 |
| marconi-llm | `query_loki` | 20 | 7,919 | 158,388 |
| marconi-llm | `query_prometheus_range` | 16 | 8,153 | 130,452 |
| marconi-llm | `query_loki_range` | 12 | 6,112 | 73,342 |
| marconi-llm | `query_prometheus` | 27 | 2,197 | 59,312 |
| marconi-llm | `get_loki_label_values` | 16 | 2,314 | 37,020 |
| marconi-llm | `docker_status` | 14 | 1,272 | 17,804 |
| marconi-llm | `list_metric_names` | 7 | 2,425 | 16,978 |
| marconi-llm | `docker_logs` | 4 | 3,660 | 14,639 |
| marconi-llm | `list_services` | 5 | 1,615 | 8,076 |

## Tool invocation counts

| tool | gemma-4-31b-it | marconi-llm |
|---|---|---|
| `docker_logs` | 4 | 4 |
| `docker_status` | 15 | 14 |
| `get_container_status` | 1 | 0 |
| `get_loki_label_values` | 8 | 16 |
| `list_metric_names` | 2 | 7 |
| `list_services` | 8 | 5 |
| `query_loki` | 6 | 20 |
| `query_loki_range` | 14 | 12 |
| `query_prometheus` | 12 | 27 |
| `query_prometheus_range` | 2 | 16 |

## Findings

### 1. gemma hallucinates tool names, but never a wrong answer

3 of 34 runs contained an invalid call. Reading the transcripts, **every one was
recovered from and every final answer was correct**:

| case | runs affected | invented name | outcome |
|---|---|---|---|
| `01_list_services:live-outofscope` | 1 of 2 | `get_container_status` | error returned, model accepted it and declined honestly |
| `03_docker_logs:live-outofscope` | 2 of 2 | `list_services` | error returned, fell back to `docker_logs`, answered from real evidence |

The two are different defects. `get_container_status` **exists nowhere in the
codebase** — a genuine fabrication, a plausible-sounding variant of
`docker_status`. `list_services` is a real tool that simply was not bound for
that case — a scoping error, not an invention.

`01` is a coin flip: one run probed the fabricated tool, the other declined
without probing. At one run per case there was a 50% chance of recording that
case as clean. `03` fails consistently in both runs.

The system prompt's rule held in all three: *"If a tool call fails with 'not a
valid tool', accept it as final: do not retry name variations."* **Zero retry
loops.** The cost of a hallucination here is one wasted call, not a bad answer.

### 2. marconi-llm never invents a tool, but emits degenerate answers

Zero invalid calls in 34 runs. That is a real advantage and it reproduces the
August result. But two runs ended in an answer that is worse than a wrong tool
call, because nothing in the output signals that the run failed:

**`05_query_prometheus_range:live-inscope`, run 2** — asked *"How has the 'up'
metric trended over the last 30 minutes?"*, made one tool call, then answered:

> The user is simply asking for a greeting.

A leaked meta-reasoning fragment, unrelated to the question. 41 characters, no
**Likely Cause**, no **Recommended Action**, 1.6s — the fastest run in the
entire suite. Run 1 of the same case answered properly in 12 turns.

**`08_all_tools:broad`, run 2** — asked *"Is anything wrong in the lab right
now?"* with **all 10 tools bound**, made **zero tool calls**, and answered:

> No visible issue. I don't have live lab telemetry, so I can only say nothing
> appears wrong from the information available here.

It claimed blindness while fully equipped. Run 1 of the same case made 9 tool
calls and produced a thorough, correct "All clear". This is the worst single
result in the suite: an operator reading it either concludes the monitoring
agent is broken, or takes "nothing appears wrong" at face value — a health
verdict with no evidence, the exact failure `manual_qa_eval.md` is written to
catch.

**This is not new.** The 2026-08-27 round recorded 2 empty final answers for
marconi-llm out of 17 runs (11.8%) and none for gemma. The same class of defect
— the model bailing out of the agent loop early and emitting a non-answer — has
now appeared in two independent rounds a month apart. It is a property of the
model, not a flake.

### 3. marconi-llm handles out-of-scope questions better

Where gemma declines flatly with 0 calls, marconi-llm declines **and** delivers
adjacent value. Asked for error logs with only Prometheus tools bound, it said
plainly *"I can only query Prometheus metrics, not raw Docker/container logs"*,
then reported every relevant error counter as flat over the window and gave the
operator the exact `docker logs --since 15m` command to run. Same pattern on
`06` (suggested `docker stats grafana` and a concrete PromQL query) and `02`
(reported the container state it could see before declining the logs part).

This is what the +69% token cost buys, and on the evidence it is worth paying.
gemma does it once — `02:live-outofscope` run 2 — but not systematically.

### 4. Memory isolation works on both models

| case | gemma | marconi-llm |
|---|---|---|
| follow-up, same thread | 0 calls, recited prior-turn evidence | 7 calls (run 1) / 0 calls (run 2), both answered |
| follow-up, fresh thread | 0 calls, asked for context — both runs | 0 calls, asked for context — both runs |

A bare *"Why? Show me the evidence for that."* answered from memory on the
continued thread and was correctly refused on a fresh one, on both models, in
all four runs. gemma is the cleaner of the two: it answered from memory with
zero tool calls, where marconi-llm re-ran a 7-call sweep in one of its runs.

### 5. `04_query_prometheus:live-outofscope` is mislabelled, not failed

The case assumes a trend cannot be derived from instant queries. Both models
disproved that — gemma by querying `rate()` at 30m/5m/1m windows, marconi-llm
by doing the same across 12 calls with a per-container breakdown. Neither
hallucinated; the case premise is wrong and should be re-worded or reclassified.

It did expose an instability worth noting: gemma's two runs, seven minutes
apart, concluded *"Gradual increase in workload"* (0.51 → 0.58 → 0.59 cores) and
*"remained stable"* respectively. Both defensible from their own data, opposite
verdicts. Trend language is not reproducible run to run.

### 6. Format compliance

| check | gemma | marconi-llm |
|---|---|---|
| empty answers | 0/34 | 0/34 |
| banned `#` headings | 0/34 | 0/34 |
| banned Markdown tables | 0/34 | 0/34 |
| missing **Likely Cause** / **Recommended Action** | 5/34 | 5/34 |

Every gemma omission is a terse decline, where the sections are arguably
meaningless. Of marconi-llm's five, two are the degenerate answers in finding 2
— so for that model a missing section is a useful failure signal, not a style
nit. The prompt says *"End every investigation with exactly two brief
sections"*; if those sections are wanted unconditionally, the wording needs to
say so for refusals too.

### 7. The latency gap is hosting, not model efficiency

marconi-llm is 2.1× faster per run **while making 1.75× the tool calls and
spending 1.69× the tokens** — 3.6× faster per 1k tokens. The cause is the
endpoint, measured directly on marconi-02:

| prompt | input tokens | output | gemma latency |
|---|---|---|---|
| tiny | 4 | 22 | 1.7s |
| tiny (repeat) | 4 | 27 | 3.2s |
| ~2k context | 1,568 | 192 | 11.2s |
| ~2k context (repeat) | 1,568 | 210 | 6.9s |

2–3s of fixed overhead on a 4-token prompt, and 2× variance on identical
prompts, which is consistent with rate-limiting on the hosted endpoint. The
tool backends are not a factor at all — `list_services` 71ms, `query_prometheus`
9ms, `get_loki_label_values` 7ms, `query_loki_range` 10ms.

Worst observed single calls: gemma spent 43.7s on one 1,468-token call and 34s
per call on another run. `ModelRetryMiddleware` retries silently, so a 429 burns
a full timeout and appears only as wall clock, never as an error.

**Do not read the duration column as a model-quality signal.** It measures where
each model is hosted. Tokens and tool-call correctness are the portable metrics.

### 8. Token sinks

Loki and Prometheus range queries dominate both models. For gemma,
`query_loki_range` alone is 102,456 of 210,234 total tokens (49%). For
marconi-llm, `query_loki` (158,388) and `query_prometheus_range` (130,452) are
81% of the suite's 354,931.

The per-invocation averages are the actionable number: 6,112–8,153 tokens for a
single range query on either model. Any cost reduction starts with trimming
what those tools return, not with changing model.

## Recommendation

**Neither model is ready to be declared the winner on n=2, and the deciding
question is narrow.**

On the metrics that matter for an ops agent, marconi-llm leads: zero invented
tool names, better out-of-scope behaviour, more thorough evidence, and faster
(for hosting reasons). gemma is cheaper in tokens and never produced a
degenerate answer.

The blocker is finding 2. A 5.9% rate of confident non-answers — one of them on
*"Is anything wrong in the lab right now?"*, the agent's core question — is
disqualifying for production **if the rate is real**. Two samples cannot
establish it, but the August round independently saw the same class of defect at
11.8%, which makes a flake unlikely.

**Next step, ~3 minutes:** re-run only that case against marconi-llm to get the
rate.

```bash
cd eval
LLM_PROVIDER=openai LLM_MODEL=marconi-llm python run_suite.py --runs 20 08_all_tools:broad
```

If the zero-call abdication reproduces above ~5%, stay on gemma and treat its
tool-name hallucination as the lesser defect — it costs a wasted call, not a
wrong answer. If it does not reproduce, marconi-llm is the better agent on every
remaining axis.

Two smaller items regardless of which model wins:

- Re-word or reclassify `04_query_prometheus:live-outofscope` (finding 5) — it
  is not measuring what it claims to.
- `03_docker_logs:live-outofscope` makes gemma reach for `list_services` in
  2/2 runs. Worth a prompt experiment: the tool is real, so the model may be
  recalling the full lab tool set rather than reading the bound list.

## Reproducing

```bash
cd /home/marconi/agent/eval
LLM_PROVIDER=google LLM_MODEL=gemma-4-31b-it python run_suite.py --runs 2
LLM_PROVIDER=openai LLM_MODEL=marconi-llm  python run_suite.py --runs 2
python analyze.py gemma-4-31b-it marconi-llm
```

Transcripts for this round are archived at `eval/logs/<model>/` on marconi-02
and mirrored locally. Run duration: gemma ~17 min, marconi-llm ~7.5 min.
