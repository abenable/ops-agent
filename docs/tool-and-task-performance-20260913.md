# Tool and task performance (2026-09-13)

Companion to `model-comparison-20260913.md`, cut along the other two axes:
**which tools cost and fail**, and **which shapes of task the agent handles
well**. Same evaluation round — 68 runs, 193 tool invocations, both models,
live backends on marconi-02.

The model comparison answers "which model". This answers "what should we fix",
and the answer is mostly not the model.

## Method

- **Reliability and cost** are extracted from the 68 transcripts in
  `eval/logs/<model>/`. A call is *failed* when its result matches
  `(tool 'NAME' failed: ...)` — the tool ran and errored. It is a *bad name*
  when the result contains `is not a valid tool` — the tool never existed.
  These are different defects and the model comparison only counted the second.
- **Latency** cannot come from the transcripts: they record duration per run,
  never per call. It is measured by calling each tool directly, 7 iterations,
  reporting the median. Same host, same live backends.
- **Token cost per tool** = the calling turn's total tokens + the next turn's
  input tokens (which carry the result), split across the calls in that turn.
- Root causes in finding 2 were reproduced by hand against the live Loki and
  Prometheus HTTP APIs, not inferred from the error text.

## Part 1 — Per-tool

### Latency, measured in isolation

| tool | p50 ms | min ms | max ms | result chars | hits cap |
|---|---|---|---|---|---|
| `docker_logs` | 39 | 30 | 43 | 4,000 | yes |
| `list_services` | 37 | 32 | 77 | 322 | no |
| `docker_status` | 36 | 31 | 42 | 72 | no |
| `list_metric_names` | 11 | 7 | 14 | 10,452 | **exceeds** |
| `query_loki` | 7 | 7 | 8 | 4,000 | yes |
| `query_loki_range` | 7 | 6 | 8 | 4,000 | yes |
| `get_loki_label_values` | 6 | 4 | 27 | 59 | no |
| `query_prometheus_range` | 4 | 4 | 5 | 4,000 | yes |
| `query_prometheus` | 3 | 3 | 3 | 988 | no |
| `get_label_values` | 2 | 2 | 4 | 88 | no |

**Tool latency is irrelevant to this agent.** The slowest tool answers in 39ms;
the median model call takes 11,400ms. Every tool is ~300× faster than the thing
that consumes its output. The Docker tools are the slowest of the ten (~36ms,
Unix-socket overhead) and it does not matter.

Optimising tool speed would buy nothing. Optimising tool *payload* is the whole
game, because payload is resent to the model on every subsequent turn.

### Reliability and cost, from the transcripts

| tool | calls | gemma / marconi | ok | failed | bad name | median result chars | at 4k cap | avg tokens per call | total tokens |
|---|---|---|---|---|---|---|---|---|---|
| `query_loki` | 26 | 6 / 20 | 24 | 2 | 0 | 4,000 | 12/24 | 7,612 | 197,904 |
| `query_loki_range` | 26 | 14 / 12 | 22 | 4 | 0 | 4,000 | 11/22 | 6,761 | 175,798 |
| `query_prometheus_range` | 18 | 2 / 16 | 15 | 3 | 0 | 1,623 | 5/15 | 7,766 | 139,785 |
| `query_prometheus` | 39 | 12 / 27 | 35 | 4 | 0 | 134 | 2/35 | 2,562 | 99,904 |
| `get_loki_label_values` | 24 | 8 / 16 | 24 | 0 | 0 | 68 | 0/24 | 2,563 | 61,524 |
| `docker_status` | 29 | 15 / 14 | 29 | 0 | 0 | 79 | 0/29 | 1,363 | 39,520 |
| `docker_logs` | 8 | 4 / 4 | 8 | 0 | 0 | 2,900 | 1/8 | 3,634 | 29,072 |
| `list_metric_names` | 9 | 2 / 7 | 9 | 0 | 0 | 1,866 | 1/9 | 2,314 | 20,824 |
| `list_services` | 13 | 8 / 5 | 11 | 0 | 2 | 322 | 0/11 | 1,534 | 19,948 |
| `get_container_status` | 1 | 1 / 0 | 0 | 0 | 1 | 0 | - | 3,402 | 3,402 |

Totals: 193 invocations, 177 ok, 13 failed (6.7%), 3 bad names, 32 results truncated at the cap (16.6%).

### Finding 1 — three tools are 65% of all token spend

`query_loki`, `query_loki_range` and `query_prometheus_range` account for
513,487 of the 787,681 tokens attributed to tools (65%). They are not the most-called
tools — `query_prometheus` is, at 39 invocations — they are the most
*expensive per call*, at 6,761–7,766 tokens each versus 1,363 for
`docker_status`.

The cause is visible in the "median result chars" column: all three return
**4,000 characters, the maximum**, on a median call. `docker_status` returns 79.
A Loki query costs roughly 5.6× a Docker status check for the same single call,
and the gap compounds because the result is re-sent on every following turn.

### Finding 2 — 13 of 193 calls failed (6.7%), and all of them are fixable

Every failure is a query the backend rejected as malformed. None are
infrastructure faults — Prometheus and Loki were healthy throughout, and the
failure rate for tools that take no query string (`docker_status`,
`get_loki_label_values`, `list_metric_names`, `docker_logs`) is **zero**.

Three root causes, each reproduced by hand against the live APIs:

**a. LogQL empty-compatible matchers — 3 failures.** Loki rejects a stream
selector whose every matcher can match the empty string:

```
{container!="loki"} |= "error"      -> parse error
{container=~".*"}   |= "error"      -> parse error
```

> queries require at least one regexp or equality matcher that does not have an
> empty-compatible value. For instance, `app=~".*"` does not meet this
> requirement, but `app=~".+"` will

Both models hit this. It is the single most common failure and the error text
names its own fix.

**b. Invalid LogQL pipeline stages — 3 failures.** `| error` is not a label
filter, `or` is not a connective between line filters, and `|= "(error"` leaves
an unbalanced parenthesis:

```
{container=~".+"} |= "error" | error               -> syntax error: unexpected $end
{...} |= "level=error" or |= "ERROR"               -> parse error
{...} |= "(error" | regex "(?i)(error|exception)"  -> parse error
```

**c. PromQL subqueries without parentheses — 7 failures.** A subquery range
cannot be applied to a bare binary expression:

```
max_over_time(1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m]))[30m:5m])
  -> binary expression must contain only scalar and instant vector types

max_over_time((1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m])))[30m:5m])
  -> 0.00626   (succeeds)
```

The only difference is one pair of parentheses.

These are query-language rules, not model defects — and neither rule appears in
the tool docstrings the model is given. That makes this the highest-leverage fix
available, and it is independent of which model ships.

### Finding 3 — results are truncated silently at 4,000 chars

`agent/tools/loki.py`, `prometheus.py` and `docker.py` all end their query tools
with `str(...)[:4000]`. **32 of 193 results (16.6%) hit that ceiling**, including
44% of all Loki queries (23 of 52).

Two problems with the current form:

1. **The model is not told.** A truncated result looks like a complete one, so
   the model may reason over a partial log window believing it is whole, or
   re-issue narrower queries to find what was actually cut — extra calls and
   extra tokens for a limit it cannot see.
2. **It cuts mid-structure.** `str(python_object)[:4000]` slices the repr, so
   the model receives a dict or list with no closing bracket, mid-key.

Appending an explicit marker — `… [truncated at 4000 chars; narrow the query]` —
costs one line per tool and tells the model both that data is missing and what
to do about it.

### Finding 4 — `list_metric_names` ignores the 4,000-char convention

Every other query tool caps at 4,000 characters. `list_metric_names` caps at
250 *names* (`"\n".join(names[:250])`), which measured **10,452 characters** on
this lab — 2.6× the ceiling every sibling tool respects, and the single largest
payload any tool can return. On a larger Prometheus it grows without bound.

## Part 2 — Per-task

Tasks grouped by how many tools the agent has to coordinate.

| task group | tools bound | model | runs | calls/run | tool failures | bad names | tokens/run | turns/run | duration/run |
|---|---|---|---|---|---|---|---|---|---|
| single-tool (01–03) | 1 | gemma-4-31b-it | 12 | 1.17 | 0 | 3 | 2,807 | 4.3 | 24.6s |
| single-tool (01–03) | 1 | marconi-llm | 12 | 1.00 | 0 | 0 | 2,528 | 4.0 | 5.1s |
| multi-tool, one backend (04–07) | 2–3 | gemma-4-31b-it | 16 | 2.31 | 1 | 0 | 8,392 | 6.4 | 31.7s |
| multi-tool, one backend (04–07) | 2–3 | marconi-llm | 16 | **5.81** | **10** | 0 | **18,525** | 11.6 | 20.6s |
| all tools (08) | 10 | gemma-4-31b-it | 6 | 3.50 | 2 | 0 | 7,047 | 7.0 | 31.5s |
| all tools (08) | 10 | marconi-llm | 6 | 2.67 | 0 | 0 | 4,700 | 5.5 | 12.0s |

Combined across both models:

| task group | runs | calls | failure rate | tokens / run |
|---|---|---|---|---|
| single-tool (01–03) | 24 | 26 | **0.0%** | 2,667 |
| multi-tool, one backend (04–07) | 32 | 130 | **8.5%** | **13,458** |
| all tools (08) | 12 | 37 | 5.4% | 5,873 |

### Finding 5 — narrow tool sets are harder than broad ones

The expected result is that difficulty rises with tool count. It does not.
**Tasks with all 10 tools bound cost less than half what 2–3 tool tasks cost**
(5,873 vs 13,458 tokens per run) and fail less often (5.4% vs 8.5%).

The mechanism is visible in the transcripts. With the right tool available, the
agent makes one correct call and answers. With only Prometheus bound and a
question about logs, it cannot answer correctly at any price, so it grinds
through query variants — `topk`, `increase`, `__name__` regex sweeps — until it
gives up. `05_query_prometheus_range:live-outofscope` cost marconi-llm 40,243
tokens and 10 calls to ultimately say "I can only query Prometheus metrics."

Two consequences:

- **The 04–07 group is measuring tool-set starvation, not agent capability.**
  Its 8.5% failure rate is a property of the eval design — deliberately
  withholding the right backend — and should not be read as a production
  failure rate. Production binds all configured tools, which is the 08 shape.
- **Do not "simplify" the production agent by narrowing its tool set.** On this
  evidence that would raise cost and failure rate, not lower them.

### Finding 6 — single-tool tasks are solved

24 runs, 26 calls, **zero tool failures**, ~1.0 call per run — the agent calls
the one right tool once and answers. The only defect in the entire group is
gemma's 3 hallucinated tool names, all recovered from (see the model comparison,
finding 1). There is nothing to optimise here.

## Recommendations

Ranked by leverage, and none of them require choosing a model:

1. **Put the query-language rules in the tool docstrings** (finding 2). State
   in `query_loki`/`query_loki_range` that a stream selector needs at least one
   non-empty-compatible matcher (`.+`, not `.*`, and never `!=` alone), and in
   `query_prometheus`/`query_prometheus_range` that a subquery range must be
   applied to a parenthesised expression. This addresses all 13 observed
   failures, costs no runtime, and helps every model.
2. **Mark truncation explicitly** (finding 3). Replace the bare `[:4000]` with
   a slice plus a marker naming the limit. 17% of results are affected and the
   model currently cannot tell.
3. **Cap `list_metric_names` by characters, not count** (finding 4), for
   consistency with the other nine tools and to bound it on larger estates.
4. **Trim Loki payloads before capping** (finding 1). The three query tools are
   74% of token spend and return the maximum payload on a median call. Returning
   fewer, more relevant lines beats any model or prompt change for cost.
5. **Re-scope the 04–07 out-of-scope cases** (finding 5). As written they
   measure how expensively a model fails when starved, which is not a production
   condition. Keep one as a deliberate starvation probe; convert the rest.

## Reproducing

Per-tool latency benchmark (7 iterations, live backends):

```bash
ssh marconi-02 'cd /home/marconi/agent && .venv/bin/python /tmp/toolbench.py'
```

Reliability, payload and token figures are derived from the transcripts in
`eval/logs/<model>/` for the 2026-09-13 round; see
`model-comparison-20260913.md` for how that round was run.
