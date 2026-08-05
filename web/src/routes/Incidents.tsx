import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { TriangleAlertIcon, CircleCheckIcon } from "lucide-react";

import { api, type Incident } from "../api";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { IncidentStatusBadge } from "@/components/status";

const FILTERS = [
  { value: "all", label: "All" },
  { value: "open", label: "Open" },
  { value: "ack", label: "Acknowledged" },
  { value: "resolved", label: "Resolved" },
];

export function Incidents() {
  const [filter, setFilter] = useState("all");
  const incidents = useQuery({
    queryKey: ["incidents", filter],
    queryFn: () => api.incidents(filter === "all" ? undefined : filter),
    refetchInterval: 10_000,
  });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-end justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="font-heading text-xl font-semibold tracking-tight">Incidents</h1>
          <p className="text-sm text-muted-foreground">
            Incident reports produced by the agentic investigation workflow.
          </p>
        </div>
        <Tabs value={filter} onValueChange={setFilter}>
          <TabsList>
            {FILTERS.map((f) => (
              <TabsTrigger key={f.value} value={f.value}>
                {f.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </div>

      {incidents.isLoading && (
        <div className="flex flex-col gap-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      )}
      {incidents.isError && (
        <Empty className="min-h-48">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <TriangleAlertIcon />
            </EmptyMedia>
            <EmptyTitle>Failed to load incidents</EmptyTitle>
            <EmptyDescription>Check that the API is reachable.</EmptyDescription>
          </EmptyHeader>
        </Empty>
      )}
      {incidents.data && incidents.data.length === 0 && (
        <Empty className="min-h-48">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <CircleCheckIcon />
            </EmptyMedia>
            <EmptyTitle>No incidents</EmptyTitle>
            <EmptyDescription>No incidents match this filter.</EmptyDescription>
          </EmptyHeader>
        </Empty>
      )}
      {incidents.data && incidents.data.length > 0 && (
        <div className="overflow-hidden rounded-xl ring-1 ring-foreground/10">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-32">ID</TableHead>
                <TableHead>Service</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Summary</TableHead>
                <TableHead className="text-right">Created</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {incidents.data.map((i) => (
                <IncidentRow key={i.id} i={i} />
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

function IncidentRow({ i }: { i: Incident }) {
  return (
    <TableRow>
      <TableCell className="font-mono text-xs text-muted-foreground">{i.id}</TableCell>
      <TableCell className="font-mono font-medium">{i.service}</TableCell>
      <TableCell>
        <IncidentStatusBadge status={i.status} />
      </TableCell>
      <TableCell className="max-w-96 truncate text-muted-foreground">{i.summary}</TableCell>
      <TableCell className="text-right text-xs text-muted-foreground">
        {new Date(i.created_at).toLocaleString()}
      </TableCell>
    </TableRow>
  );
}
