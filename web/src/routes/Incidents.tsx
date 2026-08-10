import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckIcon, TriangleAlertIcon, WrenchIcon, XIcon, CircleCheckIcon } from "lucide-react";

import {
  api,
  type Approval,
  type Incident,
  type RemediationResult,
  type ApprovalResult,
} from "../api";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { IncidentStatusBadge } from "@/components/status";
import { Markdown } from "@/components/markdown";

const FILTERS = [
  { value: "all", label: "All" },
  { value: "open", label: "Open" },
  { value: "ack", label: "Acknowledged" },
  { value: "resolved", label: "Resolved" },
];

export function Incidents() {
  const [filter, setFilter] = useState("all");
  const [fixFor, setFixFor] = useState<string | null>(null);
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
            Incident reports from the agentic investigation workflow. Resolve an incident or run the
            gated remediation agent, then approve or reject its restart proposal.
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
                <TableHead className="w-28">ID</TableHead>
                <TableHead>Service</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Summary</TableHead>
                <TableHead className="text-right">Created</TableHead>
                <TableHead className="w-44 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {incidents.data.map((i) => (
                <IncidentRow
                  key={i.id}
                  i={i}
                  fixOpen={fixFor === i.id}
                  onToggleFix={() => setFixFor((cur) => (cur === i.id ? null : i.id))}
                />
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {fixFor && <FixPanel key={fixFor} incidentId={fixFor} />}
    </div>
  );
}

function IncidentRow({
  i,
  fixOpen,
  onToggleFix,
}: {
  i: Incident;
  fixOpen: boolean;
  onToggleFix: () => void;
}) {
  const qc = useQueryClient();
  const resolve = useMutation({
    mutationFn: () => api.resolve(i.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["incidents"] }),
  });
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
      <TableCell className="text-right">
        <div className="flex justify-end gap-2">
          {i.status !== "resolved" && (
            <Button
              size="sm"
              variant={fixOpen ? "default" : "outline"}
              onClick={onToggleFix}
              disabled={resolve.isPending}
            >
              <WrenchIcon /> {fixOpen ? "Hide fix" : "Fix"}
            </Button>
          )}
          {i.status !== "resolved" && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => resolve.mutate()}
              disabled={resolve.isPending}
            >
              <CheckIcon /> Resolve
            </Button>
          )}
        </div>
      </TableCell>
    </TableRow>
  );
}

function FixPanel({ incidentId }: { incidentId: string }) {
  const qc = useQueryClient();
  const [result, setResult] = useState<RemediationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [decision, setDecision] = useState<Record<string, string>>({});

  const remediate = useMutation({
    mutationFn: () => api.remediate(incidentId),
    onSuccess: (r) => {
      setResult(r);
      setError(null);
    },
    onError: (e) => setError(String(e)),
  });

  const proposals = useQuery({
    queryKey: ["approvals", incidentId],
    queryFn: () => api.approvals(incidentId),
    enabled: !!result || remediate.isPending,
    refetchInterval: 5_000,
  });

  const act = useMutation({
    mutationFn: async ({ id, kind }: { id: string; kind: "approve" | "reject" }) =>
      kind === "approve" ? api.approve(id) : api.reject(id),
    onSuccess: (r: ApprovalResult, { id, kind }) => {
      setDecision((d) => ({ ...d, [id]: kind }));
      qc.invalidateQueries({ queryKey: ["approvals", incidentId] });
      qc.invalidateQueries({ queryKey: ["incidents"] });
      return r;
    },
  });

  return (
    <div className="rounded-xl ring-1 ring-foreground/10">
      <div className="flex items-center justify-between gap-2 border-b px-4 py-3">
        <div className="flex items-center gap-2">
          <WrenchIcon className="size-4" />
          <span className="font-medium">Remediation for incident {incidentId}</span>
        </div>
        <Button
          size="sm"
          variant={remediate.isPending ? "outline" : "default"}
          onClick={() => remediate.mutate()}
          disabled={remediate.isPending}
        >
          {remediate.isPending ? "Running remediation agent…" : result ? "Re-run remediation" : "Run remediation agent"}
        </Button>
      </div>
      <div className="flex flex-col gap-3 p-4">
        {error && <p className="text-sm text-destructive">{error}</p>}
        {!result && !error && (
          <p className="text-sm text-muted-foreground">
            Click <span className="font-medium">Run remediation agent</span> to let the gated remediator
            inspect this incident's diagnosis and propose a Docker restart (if appropriate). No restart
            runs until you approve the proposal.
          </p>
        )}
        {result && (
          <div className="rounded-md bg-muted/40 p-3 text-sm">
            <Markdown>{result.summary}</Markdown>
          </div>
        )}

        {proposals.data && proposals.data.length > 0 && (
          <div className="flex flex-col gap-2">
            <h3 className="text-sm font-medium">Pending proposals</h3>
            {proposals.data.map((a) => (
              <ProposalRow
                key={a.id}
                a={a}
                decision={decision[a.id]}
                pending={act.isPending}
                onApprove={() => act.mutate({ id: a.id, kind: "approve" })}
                onReject={() => act.mutate({ id: a.id, kind: "reject" })}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ProposalRow({
  a,
  decision,
  pending,
  onApprove,
  onReject,
}: {
  a: Approval;
  decision: string | undefined;
  pending: boolean;
  onApprove: () => void;
  onReject: () => void;
}) {
  const resolved = a.status !== "pending";
  const effective = decision ?? a.status;
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-md bg-background p-3 ring-1 ring-foreground/10">
      <div className="flex flex-col gap-0.5">
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="font-mono text-xs">{a.id}</Badge>
          <code className="font-mono text-sm">{a.container_name}</code>
        </div>
        <span className="text-xs text-muted-foreground">
          {a.action} · {new Date(a.created_at).toLocaleString()}
        </span>
      </div>
      <div className="flex items-center gap-2">
        {!resolved && !decision && (
          <>
            <Button size="sm" variant="default" onClick={onApprove} disabled={pending}>
              <CheckIcon /> Approve
            </Button>
            <Button size="sm" variant="outline" onClick={onReject} disabled={pending}>
              <XIcon /> Reject
            </Button>
          </>
        )}
        {(resolved || decision) && (
          <Badge variant={effective === "approve" || effective === "approved" ? "default" : "secondary"}>
            {effective}
          </Badge>
        )}
      </div>
    </div>
  );
}
