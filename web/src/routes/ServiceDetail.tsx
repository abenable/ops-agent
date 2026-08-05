import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { ArrowLeftIcon, CpuIcon, MemoryStickIcon, ScrollTextIcon, ShieldAlertIcon } from "lucide-react";
import { toast } from "sonner";

import { api } from "../api";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { ContainerStatusBadge } from "@/components/status";

export function ServiceDetail() {
  const { name } = useParams({ from: "/services/$name" });
  const queryClient = useQueryClient();
  const status = useQuery({ queryKey: ["status", name], queryFn: () => api.status(name) });
  const logs = useQuery({
    queryKey: ["logs", name],
    queryFn: () => api.logs(name, 100),
    refetchInterval: 15_000,
  });
  const metrics = useQuery({
    queryKey: ["metrics", name],
    queryFn: () => api.metrics(name),
    refetchInterval: 15_000,
  });
  const runIncident = useMutation({
    mutationFn: () => api.createIncident(name),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["incidents"] });
      toast.success(`Incident ${data.incident_id} created.`);
    },
    onError: () => toast.error("Failed to run incident workflow."),
  });

  const cpu = typeof metrics.data?.cpu_percent === "number" ? metrics.data.cpu_percent : undefined;
  const mem = typeof metrics.data?.memory_percent === "number" ? metrics.data.memory_percent : undefined;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="icon-sm" render={<Link to="/" />} aria-label="Back to dashboard">
          <ArrowLeftIcon />
        </Button>
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <h1 className="font-mono text-xl font-semibold tracking-tight">{name}</h1>
            {status.data && <ContainerStatusBadge state={status.data.status} />}
          </div>
          <p className="text-sm text-muted-foreground">Service status, metrics, and logs.</p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle>Status</CardTitle>
            <CardDescription>Live container state</CardDescription>
            <CardAction>
              <Button
                variant="outline"
                size="sm"
                disabled={runIncident.isPending}
                onClick={() => runIncident.mutate()}
              >
                {runIncident.isPending ? (
                  <Spinner data-icon="inline-start" />
                ) : (
                  <ShieldAlertIcon data-icon="inline-start" />
                )}
                Run incident workflow
              </Button>
            </CardAction>
          </CardHeader>
          <CardContent>
            {runIncident.data && (
              <Alert className="mb-4">
                <AlertTitle>Incident {runIncident.data.incident_id} created</AlertTitle>
                <AlertDescription className="whitespace-pre-wrap">
                  {runIncident.data.summary}
                </AlertDescription>
              </Alert>
            )}
            {status.isLoading && (
              <div className="flex flex-col gap-3">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-4 w-32" />
              </div>
            )}
            {status.data?.status === "not found" && (
              <Alert>
                <AlertTitle>Service not found</AlertTitle>
                <AlertDescription>No container matches {name}.</AlertDescription>
              </Alert>
            )}
            {status.data && status.data.status !== "not found" && (
              <dl className="flex flex-col gap-3">
                <Field label="State" value={status.data.status} />
                <Field label="Container" value={status.data.container} mono />
                <Field label="Image" value={status.data.image} mono />
                {status.data.detail && <Field label="Detail" value={status.data.detail} />}
              </dl>
            )}
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Metrics</CardTitle>
            <CardDescription>Resource usage from Prometheus</CardDescription>
          </CardHeader>
          <CardContent>
            {metrics.isLoading && (
              <div className="flex flex-col gap-3">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-2 w-full" />
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-2 w-full" />
              </div>
            )}
            {cpu === undefined && mem === undefined && metrics.data && (
              <pre className="overflow-x-auto rounded-lg bg-muted/50 p-3 font-mono text-xs text-muted-foreground">
                {JSON.stringify(metrics.data, null, 2)}
              </pre>
            )}
            {(cpu !== undefined || mem !== undefined) && (
              <div className="flex flex-col gap-6">
                <MetricBar
                  label="CPU"
                  value={cpu ?? 0}
                  icon={CpuIcon}
                  max={100}
                />
                <MetricBar
                  label="Memory"
                  value={mem ?? 0}
                  icon={MemoryStickIcon}
                  max={100}
                />
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>
            <span className="flex items-center gap-2">
              <ScrollTextIcon />
              Logs
            </span>
          </CardTitle>
          <CardDescription>Last 100 lines</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {logs.isLoading && (
            <div className="flex flex-col gap-2 p-4">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-3 w-full" />
              ))}
            </div>
          )}
          {logs.data && (
            <ScrollArea className="h-80">
              <pre className="p-4 font-mono text-xs leading-relaxed text-muted-foreground">
                {logs.data.logs || "// no log lines"}
              </pre>
            </ScrollArea>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Field({ label, value, mono }: { label: string; value?: string; mono?: boolean }) {
  if (!value) return null;
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={mono ? "font-mono text-sm" : "text-sm"}>{value}</dd>
    </div>
  );
}

function MetricBar({
  label,
  value,
  icon,
  max,
}: {
  label: string;
  value: number;
  icon: typeof CpuIcon;
  max: number;
}) {
  const Icon = icon;
  const pct = Math.min(100, Math.round((value / max) * 100));
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between text-sm">
        <span className="flex items-center gap-2 font-medium">
          <Icon className="size-4 text-muted-foreground" />
          {label}
        </span>
        <Badge variant="outline" className="tabular-nums">
          {pct}%
        </Badge>
      </div>
      <Progress value={pct} />
    </div>
  );
}
