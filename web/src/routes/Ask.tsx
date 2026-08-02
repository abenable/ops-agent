import { useState, useRef, useCallback } from "react";
import { streamAgent, type AgentEvent } from "../api";

type Turn =
  | { kind: "tool_call"; step: number; name: string; args: unknown }
  | { kind: "tool_result"; step: number; name: string; result: string }
  | { kind: "done"; text: string; incidentId?: string }
  | { kind: "error"; text: string };

export function Ask() {
  const [question, setQuestion] = useState("Investigate the agent_api service.");
  const [service, setService] = useState("");
  const [mode, setMode] = useState<"ask" | "incident">("ask");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [running, setRunning] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const onEvent = useCallback((e: AgentEvent) => {
    setTurns((prev) => {
      switch (e.type) {
        case "tool_call":
          return [...prev, { kind: "tool_call", step: e.step, name: e.name, args: e.args }];
        case "tool_result":
          return [...prev, { kind: "tool_result", step: e.step, name: e.name, result: e.result }];
        case "done":
          if ("incident_id" in e) {
            return [...prev, { kind: "done", text: e.summary, incidentId: e.incident_id }];
          }
          return [...prev, { kind: "done", text: e.content }];
        case "error":
          return [...prev, { kind: "error", text: e.message }];
      }
    });
  }, []);

  const run = async () => {
    setTurns([]);
    setRunning(true);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      if (mode === "ask") {
        await streamAgent("/ask/stream", { question }, onEvent, ctrl.signal);
      } else {
        await streamAgent(
          `/incidents/${encodeURIComponent(service)}/stream`,
          {},
          onEvent,
          ctrl.signal,
        );
      }
    } catch (err) {
      if (!ctrl.signal.aborted) {
        setTurns((prev) => [...prev, { kind: "error", text: String(err) }]);
      }
    } finally {
      setRunning(false);
      abortRef.current = null;
    }
  };

  const stop = () => abortRef.current?.abort();
  const canRun = mode === "ask" ? question.trim() : service.trim();

  return (
    <div className="max-w-[1440px] mx-auto px-6 lg:px-10 section-rhythm">
      <h1 className="text-[32px] font-medium leading-tight">Agentic investigation</h1>

      <div className="flex gap-2">
        {(["ask", "incident"] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={"chip " + (mode === m ? "chip-active" : "")}
          >
            {m === "ask" ? "Free-form ask" : "Incident workflow"}
          </button>
        ))}
      </div>

      {mode === "ask" ? (
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={2}
          className="w-full surface-cloud rounded-[24px] px-4 py-2.5 text-sm font-mono resize-none focus:outline-none focus:bg-canvas focus:ring-2 focus:ring-ink"
        />
      ) : (
        <input
          value={service}
          onChange={(e) => setService(e.target.value)}
          placeholder="service name (e.g. agent_api)"
          className="w-full surface-cloud rounded-[24px] px-4 py-2.5 text-sm font-mono focus:outline-none focus:bg-canvas focus:ring-2 focus:ring-ink"
        />
      )}

      <div className="flex gap-3">
        <button onClick={run} disabled={running || !canRun} className="btn-primary">
          {running ? "Running…" : "Run"}
        </button>
        {running && (
          <button onClick={stop} className="btn-secondary">
            Stop
          </button>
        )}
      </div>

      {/* Console transcript on the ink campaign-tile surface */}
      <section className="bg-ink text-canvas px-6 py-6 min-h-[12rem]">
        {turns.length === 0 && (
          <p className="text-stone text-sm">
            {running ? "Thinking…" : "Run an investigation to see the agent's tool calls here."}
          </p>
        )}
        <div className="space-y-3">
          {turns.map((t, idx) => (
            <TurnView key={idx} t={t} />
          ))}
        </div>
      </section>
    </div>
  );
}

function TurnView({ t }: { t: Turn }) {
  if (t.kind === "tool_call") {
    return (
      <div className="border-l-2 border-info pl-3">
        <div className="text-info font-mono text-xs">step {t.step} → {t.name}()</div>
        <pre className="text-stone text-xs mt-1 overflow-x-auto">
          {JSON.stringify(t.args, null, 2)}
        </pre>
      </div>
    );
  }
  if (t.kind === "tool_result") {
    return (
      <div className="border-l-2 border-stone pl-3">
        <div className="text-stone font-mono text-xs">← {t.name}</div>
        <pre className="text-canvas/80 text-xs mt-1 whitespace-pre-wrap max-h-48 overflow-y-auto">
          {t.result}
        </pre>
      </div>
    );
  }
  if (t.kind === "done") {
    return (
      <div className="border-l-2 border-success-bright pl-3 mt-4">
        <div className="text-[#1eaa52] font-mono text-xs mb-1">
          done{t.incidentId ? ` · incident ${t.incidentId}` : ""}
        </div>
        <p className="text-sm whitespace-pre-wrap text-canvas">{t.text}</p>
      </div>
    );
  }
  return (
    <div className="border-l-2 border-sale pl-3 text-sale text-sm">error: {t.text}</div>
  );
}
