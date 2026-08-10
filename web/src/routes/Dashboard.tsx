import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowRightIcon, BoxesIcon, CircleCheckIcon, EyeIcon, EyeOffIcon, PlusIcon, TriangleAlertIcon } from "lucide-react";
import { toast } from "sonner";

import { api, containerName, type Incident } from "../api";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ContainerStatusBadge, IncidentStatusBadge } from "@/components/status";

function StatCard({
  label,
  value,
  icon,
  tone,
  loading,
}: {
  label: string;
  value: number;
  icon: typeof BoxesIcon;
  tone?: "success" | "warning" | "destructive";
  loading: boolean;
}) {
  const Icon = icon;
  return (
    <Card size="sm">
      <CardHeader>
        <CardAction>
          <div
            className={
              "flex size-8 items-center justify-center rounded-lg " +
              (tone === "success"
                ? "bg-success/10 text-success"
                : tone === "warning"
                  ? "bg-warning/10 text-warning"
                  : tone === "destructive"
                    ? "bg-destructive/10 text-destructive"
                    : "bg-muted text-foreground")
            }
          >
            <Icon className="size-4" />
          </div>
        </CardAction>
        <CardDescription>{label}</CardDescription>
        <CardTitle className="text-2xl tabular-nums">
          {loading ? <Skeleton className="h-7 w-10" /> : value}
        </CardTitle>
      </CardHeader>
    </Card>
  );
}

export function Dashboard() {
  const queryClient = useQueryClient();
  const containers = useQuery({
    queryKey: ["containers"],
    queryFn: api.containers,
    refetchInterval: 10_000,
  });
  const watched = useQuery({ queryKey: ["watched"], queryFn: api.watched });
  const incidents = useQuery({
    queryKey: ["incidents"],
    queryFn: () => api.incidents(),
    refetchInterval: 10_000,
  });

  const toggleWatch = useMutation({
    mutationFn: async ({ name, watching }: { name: string; watching: boolean }) =>
      watching ? api.unwatch(name) : api.watch(name),
    onSuccess: (data) => {
      queryClient.setQueryData(["watched"], data);
      toast.success("Watch list updated.");
    },
    onError: () => toast.error("Failed to update watch list."),
  });

  const watching = new Set(watched.data?.containers ?? []);
  const list = containers.data ?? [];
  const running = list.filter((c) => c.State === "running").length;
  const open = (incidents.data ?? []).filter((i) => i.status === "open").length;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="font-heading text-xl font-semibold tracking-tight">Infrastructure</h1>
        <p className="text-sm text-muted-foreground">
          Live view of containers, incidents, and agentic investigations across the Marconi stack.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Containers" value={list.length} icon={BoxesIcon} loading={containers.isLoading} />
        <StatCard label="Running" value={running} icon={CircleCheckIcon} tone="success" loading={containers.isLoading} />
        <StatCard label="Watched" value={watching.size} icon={EyeIcon} loading={watched.isLoading} />
        <StatCard label="Open incidents" value={open} icon={TriangleAlertIcon} tone="destructive" loading={incidents.isLoading} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Containers</CardTitle>
          <CardDescription>
            {list.length} total · {watching.size} watched
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {containers.isLoading && (
            <div className="flex flex-col gap-3 p-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-9 w-full" />
              ))}
            </div>
          )}
          {containers.isError && (
            <Empty className="min-h-40">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <TriangleAlertIcon />
                </EmptyMedia>
                <EmptyTitle>Failed to load containers</EmptyTitle>
                <EmptyDescription>Check that the Docker daemon and API are reachable.</EmptyDescription>
              </EmptyHeader>
            </Empty>
          )}
          {containers.data && containers.data.length === 0 && (
            <Empty className="min-h-40">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <BoxesIcon />
                </EmptyMedia>
                <EmptyTitle>No containers</EmptyTitle>
                <EmptyDescription>No containers found — the Docker daemon may be unreachable.</EmptyDescription>
              </EmptyHeader>
            </Empty>
          )}
          {containers.data && containers.data.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Container</TableHead>
                  <TableHead>Image</TableHead>
                  <TableHead>State</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="w-24 text-right">Watch</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.map((c) => {
                  const name = containerName(c);
                  const isWatched = watching.has(name);
                  return (
                    <TableRow key={c.Id}>
                      <TableCell>
                        <Link
                          to="/services/$name"
                          params={{ name }}
                          className="font-mono text-sm font-medium hover:underline"
                        >
                          {name}
                        </Link>
                      </TableCell>
                      <TableCell className="max-w-48 truncate text-muted-foreground">
                        {c.Image}
                      </TableCell>
                      <TableCell>
                        <ContainerStatusBadge state={c.State} />
                      </TableCell>
                      <TableCell className="text-muted-foreground">{c.Status}</TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant={isWatched ? "secondary" : "ghost"}
                          size="sm"
                          disabled={toggleWatch.isPending}
                          onClick={() => toggleWatch.mutate({ name, watching: isWatched })}
                        >
                          {isWatched ? <EyeOffIcon /> : <PlusIcon />}
                          {isWatched ? "Watching" : "Watch"}
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Recent incidents</CardTitle>
          <CardAction>
            <Button variant="ghost" size="sm" render={<Link to="/incidents" />}>
              View all
              <ArrowRightIcon data-icon="inline-end" />
            </Button>
          </CardAction>
        </CardHeader>
        <CardContent className="p-0">
          {incidents.isLoading && (
            <div className="flex flex-col gap-3 p-4">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          )}
          {incidents.data && incidents.data.length === 0 && (
            <Empty className="min-h-40">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <CircleCheckIcon />
                </EmptyMedia>
                <EmptyTitle>All clear</EmptyTitle>
                <EmptyDescription>No incidents have been recorded.</EmptyDescription>
              </EmptyHeader>
            </Empty>
          )}
          {incidents.data && incidents.data.length > 0 && (
            <div className="flex flex-col">
              {incidents.data.slice(0, 5).map((i, idx) => (
                <div key={i.id}>
                  {idx > 0 && <Separator />}
                  <IncidentRow i={i} />
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function IncidentRow({ i }: { i: Incident }) {
  return (
    <div className="flex flex-col gap-1 px-4 py-3">
      <div className="flex items-center gap-2">
        <IncidentStatusBadge status={i.status} />
        <span className="font-mono text-sm font-medium">{i.service}</span>
        <span className="ml-auto text-xs text-muted-foreground">
          {new Date(i.created_at).toLocaleString()}
        </span>
      </div>
      <p className="line-clamp-2 text-sm text-muted-foreground">{i.summary}</p>
    </div>
  );
}
