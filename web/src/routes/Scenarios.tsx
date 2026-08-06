import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FlaskConicalIcon, PlayIcon, SquareIcon } from "lucide-react";

import { api, type Scenario, streamAgent, type AgentEvent } from "../api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { Markdown } from "@/components/markdown";
import { Spinner } from "@/components/ui/spinner";

type ToolStep = { step: number; name: string; args: unknown; result?: string };
type RunState = {
  status: "running" | "done" | "error";
  summary?: string;
  incidentId?: string;
  tools: ToolStep[];
  error?: string;
};

export function Scenarios() {
  const scenarios = useQuery({ queryKey: ["scenarios"], queryFn: api.scenarios });
  const [active, setActive] = useState<string | null>(null);
  const [run, setRun] = useState<RunState | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const runScenario = async (s: Scenario) => {
    abortRef.current?.abort();
    setActive(s.name);
    setRun({ status: "running", tools: [] });
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    const apply = (fn: (r: RunState) => RunState) => setRun((r) => (r ? fn(r) : r));
    try {
      await streamAgent(
        `/scenarios/${encodeURIComponent(s.name)}/stream`,
        {},
        (e: AgentEvent) => {
          switch (e.type) {
            case "tool_call":
              apply((r) => ({ ...r, tools: [...r.tools, { step: e.step, name: e.name, args: e.args }] }));
              break;
            case "tool_result": {
              apply((r) => {
                const tools = [...r.tools];
                const t = [...tools].reverse().find((x) => x.step === e.step && x.name === e.name);
                if (t) t.result = e.result;
                return { ...r, tools };
              });
              break;
            }
            case "done":
              apply((r) => ({
                ...r,
                status: "done",
                summary: "incident_id" in e ? e.summary : e.content,
                incidentId: "incident_id" in e ? e.incident_id : undefined,
              }));
              break;
            case "error":
              apply((r) => ({ ...r, status: "error", error: e.message }));
              break;
          }
        },
        ctrl.signal,
      );
    } catch (err) {
      if (!ctrl.signal.aborted) apply((r) => ({ ...r, status: "error", error: String(err) }));
    } finally {
      if (abortRef.current === ctrl) abortRef.current = null;
    }
  };

  const stop = () => abortRef.current?.abort();

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h1 className="font-heading text-xl font-semibold tracking-tight">Scenarios</h1>
        <p className="text-sm text-muted-foreground">
          Reproducible incident simulations mapped to real services in this stack. A run streams the
          agentic investigation live and persists an incident.
        </p>
      </div>

      {scenarios.isLoading && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-40 w-full" />
          ))}
        </div>
      )}
      {scenarios.isError && (
        <Empty className="min-h-48">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <FlaskConicalIcon />
            </EmptyMedia>
            <EmptyTitle>Failed to load scenarios</EmptyTitle>
            <EmptyDescription>Check that the API is reachable.</EmptyDescription>
          </EmptyHeader>
        </Empty>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {scenarios.data?.map((s) => (
          <Card key={s.name} className={active === s.name ? "ring-2 ring-primary" : ""}>
            <CardHeader>
              <div className="flex items-start justify-between gap-2">
                <CardTitle className="text-base">{s.title}</CardTitle>
                <Badge variant="outline" className="font-mono text-xs">{s.service}</Badge>
              </div>
              <CardDescription className="line-clamp-3">{s.symptom}</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <div className="flex flex-wrap gap-1">
                {s.expected_actions.map((a) => (
                  <Badge key={a} variant="secondary" className="font-mono text-[11px]">{a}</Badge>
                ))}
              </div>
              {active === s.name ? (
                run?.status === "running" ? (
                  <Button variant="outline" size="sm" onClick={stop}>
                    <SquareIcon /> Stop
                  </Button>
                ) : (
                  <Button variant="secondary" size="sm" onClick={() => runScenario(s)}>
                    <PlayIcon /> Run again
                  </Button>
                )
              ) : (
                <Button size="sm" onClick={() => runScenario(s)}>
                  <PlayIcon /> Run
                </Button>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      {run && (
        <div className="mt-2 rounded-xl ring-1 ring-foreground/10">
          <div className="flex items-center justify-between gap-2 border-b px-4 py-3">
            <div className="flex items-center gap-2">
              <FlaskConicalIcon className="size-4" />
              <span className="font-medium">{active}</span>
              {run.status === "running" && (
                <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Spinner className="size-3" /> investigating…
                </span>
              )}
              {run.incidentId && (
                <Badge variant="outline" className="font-mono text-xs">incident {run.incidentId}</Badge>
              )}
            </div>
            <Button variant="ghost" size="sm" onClick={() => { stop(); setRun(null); setActive(null); }}>
              Clear
            </Button>
          </div>
          <div className="flex flex-col gap-3 p-4">
            {run.tools.length > 0 && (
              <details open className="group">
                <summary className="cursor-pointer text-xs text-muted-foreground">
                  {run.tools.length} tool call{run.tools.length === 1 ? "" : "s"}
                </summary>
                <div className="mt-2 flex flex-col gap-2">
                  {run.tools.map((t, i) => (
                    <div key={i} className="rounded-md bg-muted/40 p-2">
                      <div className="flex items-center gap-2 text-xs">
                        <span className="font-mono text-muted-foreground">step {t.step}</span>
                        <code className="font-mono font-medium">{t.name}()</code>
                      </div>
                      <pre className="mt-1 overflow-x-auto rounded bg-background p-2 font-mono text-[11px] text-muted-foreground">
                        {JSON.stringify(t.args, null, 2)}
                      </pre>
                      {t.result && (
                        <pre className="mt-1 max-h-40 overflow-y-auto whitespace-pre-wrap rounded bg-background p-2 font-mono text-[11px] text-muted-foreground">
                          {t.result}
                        </pre>
                      )}
                    </div>
                  ))}
                </div>
              </details>
            )}
            {run.status === "running" && !run.summary && (
              <p className="text-sm text-muted-foreground">Waiting for the agent's diagnosis…</p>
            )}
            {run.summary && (
              <div className="rounded-md bg-muted/40 p-3 text-sm">
                <Markdown>{run.summary}</Markdown>
              </div>
            )}
            {run.status === "error" && (
              <p className="text-sm text-destructive">{run.error}</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
