import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { api, type ContainerInfo, type Incident } from "../api";

const STATE_COLORS: Record<string, string> = {
  running: "text-success",
  exited: "text-mute",
  created: "text-info",
  paused: "text-info",
  restarting: "text-info",
  dead: "text-sale",
};

export function Dashboard() {
  const queryClient = useQueryClient();
  const containers = useQuery({ queryKey: ["containers"], queryFn: api.containers });
  const watched = useQuery({ queryKey: ["watched"], queryFn: api.watched });
  const incidents = useQuery({
    queryKey: ["incidents"],
    queryFn: () => api.incidents(),
    refetchInterval: 10_000,
  });

  const toggleWatch = useMutation({
    mutationFn: async ({ name, watching }: { name: string; watching: boolean }) =>
      watching ? api.unwatch(name) : api.watch(name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["watched"] });
    },
  });

  const watching = new Set(watched.data?.containers ?? []);

  return (
    <div className="section-rhythm">
      {/* Campaign-tile hero — ink bg, display headline burned in */}
      <section className="bg-ink text-canvas px-6 py-16 md:py-24">
        <div className="max-w-[1440px] mx-auto">
          <h1 className="headline-display">INFRASTRUCTURE</h1>
          <h1 className="headline-display">OPERATIONS</h1>
          <p className="mt-6 text-stone max-w-md">
            Live view of containers, incidents, and agentic investigations across the
            Marconi stack.
          </p>
        </div>
      </section>

      <section className="max-w-[1440px] mx-auto px-6 lg:px-10">
        <div className="flex items-baseline justify-between mb-6">
          <h2 className="text-[28px] font-medium leading-none">Containers</h2>
          <span className="text-mute text-sm">
            {containers.data?.length ?? 0} total · {watching.size} watched
          </span>
        </div>
        {containers.isLoading && <p className="text-mute">Loading…</p>}
        {containers.isError && <p className="text-sale">Failed to load containers.</p>}
        {containers.data && containers.data.length === 0 && (
          <p className="text-mute">No containers (Docker daemon unreachable).</p>
        )}
        {containers.data && containers.data.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {containers.data.map((c) => (
              <ContainerCard
                key={c.Id}
                c={c}
                watched={watching.has(c.Names?.[0]?.slice(1) ?? c.Id.slice(0, 12))}
                onToggle={(name, isWatched) =>
                  toggleWatch.mutate({ name, watching: isWatched })
                }
              />
            ))}
          </div>
        )}
      </section>

      <section className="max-w-[1440px] mx-auto px-6 lg:px-10">
        <div className="flex items-baseline justify-between mb-6">
          <h2 className="text-[28px] font-medium leading-none">Recent incidents</h2>
          <Link to="/incidents" className="text-[15px] font-medium underline underline-offset-4">
            View all →
          </Link>
        </div>
        {incidents.isLoading && <p className="text-mute">Loading…</p>}
        {incidents.data && incidents.data.length === 0 && (
          <p className="text-mute">No incidents recorded.</p>
        )}
        {incidents.data && incidents.data.length > 0 && (
          <div className="grid gap-0">
            {incidents.data.slice(0, 5).map((i) => (
              <IncidentRow key={i.id} i={i} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function ContainerCard({
  c,
  watched,
  onToggle,
}: {
  c: ContainerInfo;
  watched: boolean;
  onToggle: (name: string, isWatched: boolean) => void;
}) {
  const name = c.Names?.[0]?.slice(1) ?? c.Id.slice(0, 12);
  const state = c.State ?? "unknown";
  return (
    <Link
      to="/services/$name"
      params={{ name }}
      className="card-flat block hover:bg-cloud transition-colors"
    >
      {/* Photo stage — cloud surface with state glyph */}
      <div className="surface-cloud aspect-square flex items-center justify-center">
        <span className={"font-display text-5xl leading-none " + (STATE_COLORS[state] ?? "text-ink")}>
          {state.slice(0, 4).toUpperCase()}
        </span>
      </div>
      <div className="px-3 py-3 space-y-1">
        <div className="font-mono text-sm font-medium truncate">{name}</div>
        <div className="text-xs text-mute truncate">{c.Image}</div>
        <div className="text-sm font-medium">
          <span className={STATE_COLORS[state] ?? "text-ink"}>{state}</span>
          <span className="text-mute"> · {c.Status}</span>
        </div>
        <button
          type="button"
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onToggle(name, watched);
          }}
          className={"chip mt-1 " + (watched ? "chip-active" : "")}
        >
          {watched ? "👁 watching" : "＋ watch"}
        </button>
      </div>
    </Link>
  );
}

const STATUS_COLORS: Record<string, string> = {
  open: "text-sale",
  ack: "text-mute",
  resolved: "text-success",
};

function IncidentRow({ i }: { i: Incident }) {
  return (
    <div className="card-flat px-0 py-5 hairline-b">
      <div className="flex items-center justify-between">
        <span className="font-mono text-xs text-mute">{i.id}</span>
        <span className={"text-xs font-medium " + (STATUS_COLORS[i.status] ?? "text-ink")}>
          {i.status.toUpperCase()}
        </span>
      </div>
      <div className="font-mono text-sm mt-1">{i.service}</div>
      <p className="text-sm text-mute mt-1 line-clamp-2">{i.summary}</p>
    </div>
  );
}
