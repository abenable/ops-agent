// API client. In dev the Vite proxy forwards /api -> http://localhost:8000,
// so no CORS or absolute URL is needed. Set VITE_API_BASE for a deployed backend.
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api";

export type ContainerInfo = {
  Id: string;
  Names: string[];
  Image: string;
  State: string;
  Status: string;
};

export type ServiceStatus = {
  service: string;
  container?: string;
  status: string;
  detail?: string;
  image?: string;
};

export type ServiceLogs = { service: string; lines: number; logs: string };

// get_service_metrics returns either the raw Prometheus instant-query envelope
// or a {service, message} fallback (no Prometheus data / unreachable). It never
// produces cpu_percent/memory_percent — there is no percentage-shaped metric.
export type PrometheusSeries = { metric: Record<string, string>; value?: [number, string] };
export type ServiceMetrics =
  | { service?: string; message: string }
  | { status?: string; data?: { resultType?: string; result: PrometheusSeries[] } };

export type Incident = {
  id: string;
  service: string;
  summary: string;
  status: string;
  thread_id: number | null;
  created_at: string;
};

export type IncidentResult = { incident_id: string; summary: string };

export type WatchList = { containers: string[] };

export type Task = {
  name: string;
  title: string;
  service: string;
  symptom: string;
  expected_actions: string[];
};

export type Approval = {
  id: string;
  incident_id: string;
  container_name: string;
  container_id: string;
  action: string;
  status: string;
  created_at: string;
};

export type RemediationResult = {
  incident_id: string;
  summary: string;
  proposals: Approval[];
};

export type ApprovalResult = { ok: boolean; error?: string; approval?: Approval; result?: unknown };

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

async function send<T>(method: string, path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { method });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

async function postJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

export const api = {
  containers: () => get<ContainerInfo[]>("/containers"),
  watched: () => get<WatchList>("/watch/containers"),
  watch: (name: string) => send<WatchList>("PUT", `/watch/containers/${encodeURIComponent(name)}`),
  unwatch: (name: string) => send<WatchList>("DELETE", `/watch/containers/${encodeURIComponent(name)}`),
  status: (s: string) => get<ServiceStatus>(`/services/${encodeURIComponent(s)}/status`),
  logs: (s: string, lines = 50) =>
    get<ServiceLogs>(`/services/${encodeURIComponent(s)}/logs?lines=${lines}`),
  metrics: (s: string) => get<ServiceMetrics>(`/services/${encodeURIComponent(s)}/metrics`),
  incidents: (status?: string) =>
    get<Incident[]>(`/incidents${status ? `?status=${status}` : ""}`),
  incident: (id: string) => get<Incident | null>(`/incidents/${id}`),
  createIncident: (s: string) => send<IncidentResult>("POST", `/incidents/${encodeURIComponent(s)}`),
  tasks: () => get<Task[]>("/tasks"),
  approvals: (incidentId?: string) =>
    get<Approval[]>(`/approvals${incidentId ? `?incident_id=${incidentId}` : ""}`),
  remediate: (incidentId: string) => postJson<RemediationResult>(`/incidents/${incidentId}/remediate`),
  approve: (id: string) => postJson<ApprovalResult>(`/approvals/${id}/approve`),
  reject: (id: string) => postJson<ApprovalResult>(`/approvals/${id}/reject`),
  resolve: (id: string) => postJson<Incident>(`/incidents/${id}/resolve`),
};

export function containerName(c: ContainerInfo): string {
  return c.Names?.[0]?.slice(1) ?? c.Id.slice(0, 12);
}

export type IncidentStatus = "open" | "ack" | "resolved";

// SSE event stream from the agentic investigation loop.
export type AgentEvent =
  | { type: "tool_call"; step: number; name: string; args: Record<string, unknown> }
  | { type: "tool_result"; step: number; name: string; result: string }
  | { type: "done"; content: string }
  | { type: "done"; incident_id: string; summary: string }
  | { type: "error"; message: string };

// SSE event stream of agent log activity.
export type ActivityEvent = {
  ts: number;
  level: string;
  logger: string;
  message: string;
};

export async function streamAgent(
  path: string,
  body: unknown,
  onEvent: (e: AgentEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`${res.status} ${await res.text()}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const line = frame.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      try {
        onEvent(JSON.parse(line.slice(6)) as AgentEvent);
      } catch {
      }
    }
  }
}

export async function streamActivity(
  onEvent: (e: ActivityEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const res = await fetch(`${BASE}/activity/stream`, { signal });
  if (!res.ok || !res.body) throw new Error(`${res.status} ${await res.text()}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const line = frame.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      try {
        onEvent(JSON.parse(line.slice(6)) as ActivityEvent);
      } catch {
      }
    }
  }
}
