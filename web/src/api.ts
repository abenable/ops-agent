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

export type ServiceMetrics = Record<string, unknown> & {
  service?: string;
};

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
};

export function containerName(c: ContainerInfo): string {
  return c.Names?.[0]?.slice(1) ?? c.Id.slice(0, 12);
}

export type IncidentStatus = "open" | "ack" | "resolved";

export function isHealthyState(state: string | undefined): boolean {
  return state === "running";
}

// SSE event stream from the agentic investigation loop.
export type AgentEvent =
  | { type: "tool_call"; step: number; name: string; args: Record<string, unknown> }
  | { type: "tool_result"; step: number; name: string; result: string }
  | { type: "done"; content: string }
  | { type: "done"; incident_id: string; summary: string }
  | { type: "error"; message: string };

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
        // ponytail: skip malformed chunk rather than abort the whole stream
      }
    }
  }
}
