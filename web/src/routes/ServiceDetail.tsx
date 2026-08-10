import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { ActivityIcon, ArrowLeftIcon, ScrollTextIcon, ShieldAlertIcon } from "lucide-react";
import { toast } from "sonner";

import { api, type PrometheusSeries } from "../api";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { ContainerStatusBadge } from "@/components/status";

export function ServiceDetail() {
  const { name } = useParams({ from: "/services/$name" });
  const queryClient = useQueryClient();
  const status = useQuery({
    queryKey: ["status", name],
    queryFn: () => api.status(name),
    refetchInterval: 10_000,
  });
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

  const metricMessage = metrics.data && "message" in metrics.data ? metrics.data.message : undefined;
  const metricSeries = metrics.data && "data" in metrics.data ? (metrics.data.data?.result ?? []) : [];

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
            {!metrics.isLoading && metricMessage && (
              <p className="text-sm text-muted-foreground">{metricMessage}</p>
            )}
            {!metrics.isLoading && metricSeries.length > 0 && (
              <div className="flex flex-col gap-2">
                {metricSeries.map((s, i) => (
                  <MetricRow key={i} series={s} />
                ))}
              </div>
            )}
            {!metrics.isLoading && !metricMessage && metricSeries.length === 0 && metrics.data && (
              <pre className="overflow-x-auto rounded-lg bg-muted/50 p-3 font-mono text-xs text-muted-foreground">
                {JSON.stringify(metrics.data, null, 2)}
              </pre>
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

// Renders one Prometheus vector series as-is: a label built from its metric
// labels (or "value" when unlabeled, e.g. our unscoped avg() query) and its
// raw value. No percentage bar — the backend has no 0-100-scaled metric, so
// showing one here would fabricate a number the source data never provided.
function MetricRow({ series }: { series: PrometheusSeries }) {
  const label = Object.entries(series.metric ?? {})
    .map(([k, v]) => `${k}=${v}`)
    .join(", ") || "value";
  const raw = series.value?.[1];
  const value = raw === undefined ? "—" : Number.isNaN(Number(raw)) ? raw : Number(raw).toLocaleString();
  return (
    <div className="flex items-center justify-between gap-2 text-sm">
      <span className="flex items-center gap-2 font-medium">
        <ActivityIcon className="size-4 text-muted-foreground" />
        {label}
      </span>
      <Badge variant="outline" className="tabular-nums">
        {value}
      </Badge>
    </div>
  );
}
