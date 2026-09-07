# Speaker notes: Marconi Ops Agent presentation

Deck: `docs/presentation.html` (open in browser, arrow keys / space to navigate).
Backup deep-dive: `docs/architecture-diagram.html` (only pull up if asked to zoom into architecture).

Live check before presenting (2026-09-07): marconi-02 running commit `e1bdada`,
same as this deck. Bot connected as Oracle#2421, 10 slash commands synced,
api /health returning 200, background digest already firing. Deck matches
reality, no caveat needed there.

---

## 1. Title

Just the framing: internal tool, internship project. Don't linger.

## 2. The problem (before/after)

- Before: three tools (docker, Grafana, Loki), by hand, no record of the path
  you took to a conclusion.
- After: one question in Discord, agent runs the same checks itself, answer
  comes with the evidence attached.
- Say "with tools, not memory" deliberately if asked about hallucination,
  it sets up slide 6.

## 3. What it does (demo transcript)

- Walk the transcript top to bottom: three tool calls, then a three-part
  answer (what happened / likely cause / next steps).
- Mention slash commands only in passing: the conversational path is the
  headline feature, commands are the structured escape hatch.
- HTTP API is optional, same core, not the main story. One sentence is enough.

## 4. Runs unprompted (background jobs)

- This is the thing a chat-only demo wouldn't show: it posts on its own.
- If asked how you know it works, point at tonight's live check: a
  status update already posted to #status-updates 8 minutes after the
  container started.

## 5. Architecture

- One line: every entry point (Discord, HTTP API, background monitor) feeds
  the *same* agent instance, not three implementations of similar logic.
- If pressed on why one instance, say consistency: a fix to the agent's
  behavior applies everywhere at once, no drift between surfaces.
- Have `architecture-diagram.html` ready to open if they want the detailed
  version, but don't open it unprompted.

## 6. Read-only by design

- The safety claim is structural, not policy: there is no tool in the
  10-tool surface that can mutate anything. The model can't "decide" to be
  unsafe because the capability isn't there to call.
- If asked what happens if the model tries anyway: there's nothing to try,
  the tool doesn't exist.

## 7. Evaluation (the numbers slide, expect the most questions here)

Numbers, verified against `docs/model-comparison-20260827.md`:

| metric | gemma-4-31b-it | marconi-llm |
|---|---|---|
| tokens/run | 3,982 | 6,891 (+73%) |
| duration/run | 30.5s | 7.2s (4.3x faster) |
| hallucinated tool calls | 0.12/run | 0.00/run |
| empty final answers | 0 | 2 of 17 (11.8%) |

Anticipated questions:
- **"More tokens but faster, why?"** Fewer, better-targeted tool calls;
  gemma sometimes improvises extra queries to compensate for not finding the
  right one first try (see model-comparison doc, "History" section, the
  seven-query trend example). Different axis, not a contradiction.
- **"Why recommend marconi-llm despite the empty-answer bug?"** It's the
  more correctable defect: a retry-on-empty middleware rule (already
  scoped in slide 8 / eval-plan.md) fixes it outright. Hallucinated tool
  calls, gemma's failure mode, are harder to eliminate structurally.
- **"Is this production-ready?"** No. Conditional recommendation, contingent
  on fixing the empty-answer quirk first. Say this before they ask.
- **"How rigorous is one comparison run?"** Not very, and it's worth saying
  so before they ask. 17 cases, temperature 0, single pass. Slide 8 item 4
  already flags re-running 3x per model as a to-do.

## 8. Wrap-up / what's next

Four items, all traceable to `docs/eval-plan.md` (proposed, not yet built):
1. Diagnose the empty-answer quirk before switching production over.
2. Trim Loki responses: `query_loki` alone averages 10.5k tokens/call.
3. Fix the tool-call budget dead end. A run that hits the limit should
   still summarize what it found so far, not just stop.
4. Re-run the eval suite 3x per model: one pass at temp 0 proves nothing.

If asked what the plan is for these: `eval-plan.md` already proposes
turning the harness into an automated go/no-go gate (pure-function graders
over transcript JSON, no agent, network, or Docker needed to re-run a
grade). That's the next phase, not started yet.

Close with "Thank you. Questions welcome," then stop talking.

---

## Timing

8 slides, roughly 1 min each on the walkthrough, more on slide 7. Budget
8-10 min talk plus Q&A.
