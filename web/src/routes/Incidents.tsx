import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type Incident } from "../api";

const FILTERS: (string | null)[] = [null, "open", "ack", "resolved"];

export function Incidents() {
  const [status, setStatus] = useState<string | undefined>(undefined);
  const incidents = useQuery({
    queryKey: ["incidents", status],
    queryFn: () => api.incidents(status),
    refetchInterval: 10_000,
  });

  return (
    <div className="max-w-[1440px] mx-auto px-6 lg:px-10 section-rhythm">
      <h1 className="text-[32px] font-medium leading-tight">Incidents</h1>

      <div className="flex flex-wrap gap-2">
        {FILTERS.map((f) => {
          const active = status === (f ?? undefined);
          return (
            <button
              key={f ?? "all"}
              onClick={() => setStatus(f ?? undefined)}
              className={"chip " + (active ? "chip-active" : "")}
            >
              {f ?? "all"}
            </button>
          );
        })}
      </div>

      <section>
        {incidents.isLoading && <p className="text-mute">Loading…</p>}
        {incidents.data && incidents.data.length === 0 && (
          <p className="text-mute">No incidents.</p>
        )}
        {incidents.data && incidents.data.length > 0 && (
          <div className="grid gap-0">
            {incidents.data.map((i) => (
              <IncidentCard key={i.id} i={i} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

const STATUS_COLORS: Record<string, string> = {
  open: "text-sale",
  ack: "text-mute",
  resolved: "text-success",
};

function IncidentCard({ i }: { i: Incident }) {
  return (
    <div className="card-flat px-0 py-5 hairline-b">
      <div className="flex items-center justify-between">
        <span className="font-mono text-xs text-mute">{i.id}</span>
        <span className={"text-xs font-medium " + (STATUS_COLORS[i.status] ?? "text-ink")}>
          {i.status.toUpperCase()}
        </span>
      </div>
      <div className="font-mono text-base mt-1">{i.service}</div>
      <div className="text-xs text-mute mt-0.5">{i.created_at}</div>
      <p className="text-sm text-charcoal mt-2 whitespace-pre-wrap">{i.summary}</p>
    </div>
  );
}
