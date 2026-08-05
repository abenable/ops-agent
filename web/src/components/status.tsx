import { CircleCheckIcon, CircleDotIcon, ClockIcon, TriangleAlertIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { IncidentStatus } from "@/api";

function dotClass(className: string) {
  return cn("size-2 rounded-full shrink-0", className);
}

export function ContainerStatusBadge({ state }: { state: string }) {
  switch (state) {
    case "running":
      return (
        <Badge variant="outline" className="gap-1.5 text-success">
          <span className={dotClass("bg-success")} />
          running
        </Badge>
      );
    case "created":
    case "paused":
    case "restarting":
      return (
        <Badge variant="outline" className="gap-1.5 text-warning">
          <span className={dotClass("bg-warning")} />
          {state}
        </Badge>
      );
    case "dead":
    case "exited":
      return (
        <Badge variant="destructive" className="gap-1.5">
          <TriangleAlertIcon />
          {state}
        </Badge>
      );
    default:
      return (
        <Badge variant="outline" className="gap-1.5 text-muted-foreground">
          <span className={dotClass("bg-muted-foreground")} />
          {state ?? "unknown"}
        </Badge>
      );
  }
}

export function IncidentStatusBadge({ status }: { status: IncidentStatus | string }) {
  switch (status) {
    case "open":
      return (
        <Badge variant="destructive" className="gap-1.5">
          <TriangleAlertIcon />
          open
        </Badge>
      );
    case "ack":
      return (
        <Badge variant="outline" className="gap-1.5 text-warning">
          <ClockIcon />
          ack
        </Badge>
      );
    case "resolved":
      return (
        <Badge variant="outline" className="gap-1.5 text-success">
          <CircleCheckIcon />
          resolved
        </Badge>
      );
    default:
      return (
        <Badge variant="secondary" className="gap-1.5">
          <CircleDotIcon />
          {status}
        </Badge>
      );
  }
}
