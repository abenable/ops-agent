# Documentation

Reference documentation for the Marconi Infrastructure Operations Agent.

## Start here

| Document | What it covers |
| --- | --- |
| [architecture.md](architecture.md) | System overview, layer map, request flow, data model, design decisions |
| [agent-loop.md](agent-loop.md) | The LangGraph tool-calling engine and conversation memory in detail |
| [tools.md](tools.md) | The ten read-only tools, their limits, and how names are resolved |
| [monitoring.md](monitoring.md) | The background poll loop, alerting, the event log, and scheduled digests |
| [usage.md](usage.md) | Discord commands and conversational use |
| [configuration.md](configuration.md) | Every environment variable, its default, and its effect |
| [deployment.md](deployment.md) | Running locally and with the container stack |
| [development.md](development.md) | Project layout, tests, evaluation notebooks, extending the agent |
| [evaluation.md](evaluation.md) | The notebook harness that probes model behaviour against live backends |

## Report

[pdf/report.pdf](pdf/report.pdf) is a standalone report on the design and implementation
of the system, written for readers without access to this repository. Its source is
[pdf/report.tex](pdf/report.tex) and it builds with `pdflatex report.tex` run twice from
inside `docs/pdf`.
