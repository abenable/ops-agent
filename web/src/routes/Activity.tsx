import { useEffect, useRef, useState } from "react";
import { ActivityIcon, PauseIcon, PlayIcon } from "lucide-react";

import { streamActivity, type ActivityEvent } from "../api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const LEVEL_TONE: Record<string, string> = {
  INFO: "text-muted-foreground",
  WARNING: "text-amber-500",
  ERROR: "text-destructive",
  CRITICAL: "text-destructive",
};

export function Activity() {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [paused, setPaused] = useState(false);
  const pausedRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    pausedRef.current = paused;
  }, [paused]);

  useEffect(() => {
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    streamActivity((e) => {
      if (pausedRef.current) return;
      setEvents((prev) => [...prev.slice(-499), e]);
    }, ctrl.signal).catch(() => {});
    return () => ctrl.abort();
  }, []);

  useEffect(() => {
    if (!paused) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events, paused]);

  return (
    <div className="flex h-[calc(100svh-6.5rem)] min-h-96 flex-col gap-3">
      <div className="flex items-end justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="font-heading text-xl font-semibold tracking-tight">Agent activity</h1>
          <p className="text-sm text-muted-foreground">
            Live INFO+ log stream from the agent (tool calls, workflow steps, API requests) in this
            API process. Mirrors the <code className="font-mono">#agent-logs</code> Discord channel.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="gap-1.5">
            <span className={cn("size-1.5 rounded-full", paused ? "bg-muted-foreground" : "bg-success animate-pulse")} />
            {paused ? "Paused" : "Live"}
          </Badge>
          <Button variant="outline" size="sm" onClick={() => setPaused((p) => !p)}>
            {paused ? <PlayIcon /> : <PauseIcon />}
            {paused ? "Resume" : "Pause"}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setEvents([])}>
            Clear
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto rounded-xl bg-muted/30 p-3 ring-1 ring-foreground/10">
        {events.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            <ActivityIcon className="mr-2 size-4" /> Waiting for agent activity…
          </div>
        ) : (
          <div className="flex flex-col gap-0.5 font-mono text-xs">
            {events.map((e, i) => (
              <div key={i} className="flex gap-2 hover:bg-muted/50">
                <span className="shrink-0 text-muted-foreground/70">
                  {new Date(e.ts * 1000).toLocaleTimeString(undefined, { hour12: false })}
                </span>
                <span className={cn("w-16 shrink-0 font-semibold", LEVEL_TONE[e.level] ?? "")}>
                  {e.level}
                </span>
                <span className="shrink-0 text-primary/70">{e.logger}</span>
                <span className="whitespace-pre-wrap break-words">{e.message}</span>
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>
    </div>
  );
}
