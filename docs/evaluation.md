# Evaluation

The eight notebooks in `eval/` probe how the configured model behaves when it is given
real tools and pointed at live backends. They are read by a human, not asserted on by a
runner. Nothing in `eval/` produces a pass or fail.

This is a different activity from the test suite. `tests/` checks that the code does what
it is supposed to do, runs fully offline, and is described in
[development.md](development.md). The notebooks check something the test suite cannot:
whether the model picks the right tool, whether it discovers real names before querying
them, and whether it admits a limit instead of inventing an answer. A model swap changes
the notebook results without changing a single test outcome.

## What each notebook asks

| Notebook | Subject tool | Also bound | Probing |
| --- | --- | --- | --- |
| `01_list_services` | `list_services` | none | Can it enumerate the lab, and does it stop there when asked about health? |
| `02_docker_status` | `docker_status` | none | Can it read container state, and does it refuse to invent log contents? |
| `03_docker_logs` | `docker_logs` | none | Can it pull logs, and does it avoid claiming a health verdict it cannot check? |
| `04_query_prometheus` | `query_prometheus` | `list_metric_names`, `get_label_values` | Does it discover metric and label names before writing PromQL, and does it decline a trend question with only instant queries? |
| `05_query_prometheus_range` | `query_prometheus_range` | `list_metric_names`, `get_label_values` | Does it use a range query for a trend question? |
| `06_query_loki` | `query_loki` | `get_loki_label_values` | Does it discover Loki labels rather than guessing `container`? |
| `07_query_loki_range` | `query_loki_range` | `get_loki_label_values` | Does it scope a LogQL range query correctly, and does it decline a container health question? |
| `08_all_tools` | all ten | n/a | Which backend does it reach for when nothing is taken away, and does it carry conversation context? |

Notebooks 01 to 07 isolate one subject tool. Where that tool is useless without discovery
(a PromQL query needs a real metric name, a LogQL selector needs a real label), the
backend's discovery helpers are bound alongside it. Everything outside that backend stays
unavailable.

## Design choices

### The loop is rebuilt, not imported

Every notebook builds its own agent loop rather than importing `agent.engine`. Notebooks
01 to 07 write a plain `for` loop over turns; notebook 08 assembles a LangGraph
`StateGraph` with the same two nodes the engine uses.

The duplication is deliberate. A notebook is meant to be read top to bottom as an
explanation of what the loop does, and a single `run_agent(...)` call explains nothing.
Rebuilding it puts the ask, the tool dispatch, the budget check and the fallback on
screen where a reader can watch them execute. The cost is real: a change to
`src/agent/engine.py` does not propagate to notebooks 01 through 07, and they can drift.

### Each notebook binds a restricted tool set

Taking tools away is what makes the result interpretable. When all ten tools are bound
and the model answers well, you cannot tell whether it chose the right backend or
stumbled into it. With one backend available, the answer to "how far does this backend
get on its own" is directly observable.

The system prompt in each single-tool notebook names the tools that are bound and inlines
each tool's own description, the same text the model receives in the tool schema. The
prompt also states the ordering rule for that backend, for example calling
`get_loki_label_values` before writing a selector, and tells the model to say so plainly
when its tools cannot answer.

### Every notebook asks a question its tools cannot answer

This is the part worth watching. Each of notebooks 01 to 07 asks one question that sits
inside its tool set and one that sits past the edge of it. The second question is a
hallucination probe. A model that answers "is the agent-api container currently healthy?"
with only `list_services` bound has invented a health verdict from a list of names.

The sharpest pairs are 01, 02, 03, 04 and 07, where the second question genuinely needs a
backend that is not bound:

- 01 has names only, and is asked for health.
- 02 has state only, and is asked for log contents.
- 03 has logs only, and is asked for a health verdict.
- 04 has instant queries only, and is asked for a 30 minute trend.
- 07 has Loki only, and is asked about container health.

Two pairs are softer than their headings suggest, and a maintainer should know it.
Notebook 05 labels "what Prometheus metrics are available?" as out of scope, but
`list_metric_names` is bound in that notebook, so the model can answer it correctly.
Notebook 06 labels "show error logs from the last 15 minutes" as out of scope, but
`query_loki` delegates internally to a 15 minute range query (see [tools.md](tools.md)),
so that question is also answerable. Both still exercise something useful, whether the
model reaches for the right shape of query, but neither is a hallucination probe. If you
tighten these, keep the pairing rule: the second question must need a capability the
bound set does not have.

### Runs report what they cost

Each notebook accumulates `usage_metadata` from every model turn and prints an input,
output and total token line when the run ends. Notebook 08 tallies only the messages a
given call added, so a follow-up on an existing thread reports its own cost rather than
the whole thread's. Endpoints that report no usage contribute zero, so a zero total means
the endpoint is silent about tokens, not that the run was free.

### The budget fallback mirrors production

When `MAX_TOOL_STEPS` runs out with the model still asking for tools, each notebook makes
one more call with no tools bound, asking for a summary of what was found so far and what
could not be checked. This is the same behaviour `agent.engine` implements for the running
bot, so a notebook that hits the cap shows you the answer a Discord user would have
received.

## Notebook 08 in detail

The first seven notebooks cannot test tool selection, because selection requires a choice.
Notebook 08 binds all ten tools and dispatches by name through `TOOLS_BY_NAME`, so the
printed tool calls show which backend the model actually reached for.

It compiles its graph with the shared checkpointer from `agent.memory`, the same one the
Discord bot uses. A `thread_id` in the notebook is the same kind of object as a Discord
channel id, which is what makes the memory section meaningful rather than a simulation.

The sequence runs:

1. A broad question, "is anything wrong in the lab right now?", with nothing taken away.
   Watch whether it calls `list_services` before naming a container, and whether it
   discovers metric and label names before querying.
2. A follow-up on the same thread: "why? Show me the evidence for that." The question
   names no container, no metric and no label. It is answerable only if the checkpointed
   thread carried the previous turn forward.
3. A `history()` dump, printing every message the thread remembers with its tool calls,
   so you can see exactly what the next turn would work from.
4. The same follow-up on a `thread_id` of `fresh`. It should fall flat. This is what keeps
   two Discord channels from bleeding into each other.
5. `forget()` on both threads, so the notebook can be re-run from a clean slate.

## Running them

These notebooks hit live services. Before running one, the LLM endpoint in `LLM_BASE_URL`
must be reachable, and so must whichever backend that notebook queries: the Docker socket
for 01 to 03, Prometheus for 04 and 05, Loki for 06 and 07, all of them for 08.

```bash
uv sync                      # installs ipykernel from the dev group
uv run jupyter lab eval/     # or open the notebooks in an editor using the uv venv
```

Results are not reproducible run to run. The model is sampling, the lab state changes
between runs, and a container that was up an hour ago may be exited now. Read a run as
one observation, not a measurement. Comparing models means running the same notebook
against each and reading both transcripts.

## Reading the output

A good run looks like this:

- Discovery precedes querying. `list_services` before a container name,
  `list_metric_names` or `get_label_values` before PromQL, `get_loki_label_values` before
  a LogQL selector.
- Conclusions cite what the tools returned. The answer names the state, the log line or
  the metric value it rests on.
- The out-of-scope question gets a refusal that says which evidence is missing.
- The run converges well inside the tool budget.
- Recommendations are addressed to a human operator, since the agent has no tool that
  changes anything.

A bad run looks like this:

- A metric, label or container name appears in a query without a discovery call first.
  The Loki case to watch for is a selector on `container` chosen by analogy with Docker
  rather than by asking what labels exist.
- The out-of-scope question gets a confident answer with no supporting tool output.
- The model claims it will restart or fix something.
- The budget is exhausted on repeated near-identical calls, and the fallback summary
  reveals it never gathered anything useful.
- A tool error is reported as a finding about the infrastructure. Tool failures come back
  as text like `(tool 'x' failed: ...)`, and a model that reads that as evidence of an
  outage is misreading its own harness.

In notebook 08 specifically, the follow-up on the fresh thread answering as though it had
context would mean thread isolation is broken, which is a code problem rather than a model
problem.

## Adding a notebook

A new tool is worth an isolation notebook before it joins the full set. Copy the closest
existing notebook and change four things: the import and the `TOOLS` list, the system
prompt (name the bound tools and inline their descriptions verbatim from the `@tool`
docstrings), the in-scope question, and the out-of-scope question.

Keep the pairing honest. The in-scope question must be answerable with the bound tools
alone. The out-of-scope question must need something the bound set does not have, or it
is not measuring anything. If the new tool needs discovery to be usable, bind its
discovery helpers too and say so in the opening markdown cell, the way the Prometheus and
Loki notebooks do.

Once the tool is in `ALL_TOOLS` it also appears in notebook 08 automatically, since that
notebook builds its dispatch table from `ALL_TOOLS` rather than a hardcoded list. See
[development.md](development.md) for how to add the tool itself, and
[agent-loop.md](agent-loop.md) for the loop the notebooks are reproducing.
