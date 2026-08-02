import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { api } from "../api";

export function ServiceDetail() {
  const { name } = useParams({ from: "/services/$name" });
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

  return (
    <div className="section-rhythm max-w-[1440px] mx-auto px-6 lg:px-10">
      <Link to="/" className="text-sm text-mute hover:text-ink underline underline-offset-4">
        ← Dashboard
      </Link>

      <h1 className="text-[32px] font-medium leading-tight font-mono">{name}</h1>

      <section>
        <h2 className="text-[15px] font-medium mb-3 text-mute">STATUS</h2>
        <div className="hairline-b pb-4">
          {status.isLoading && <p className="text-mute">Loading…</p>}
          {status.data && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-y-3 gap-x-8 text-sm">
              <Field label="state" value={status.data.status} />
              {status.data.container && <Field label="container" value={status.data.container} />}
              {status.data.image && <Field label="image" value={status.data.image} />}
              {status.data.detail && <Field label="detail" value={status.data.detail} />}
            </div>
          )}
        </div>
      </section>

      <section>
        <h2 className="text-[15px] font-medium mb-3 text-mute">METRICS</h2>
        <pre className="surface-cloud p-4 text-xs font-mono overflow-x-auto">
          {metrics.data ? JSON.stringify(metrics.data, null, 2) : "loading…"}
        </pre>
      </section>

      <section>
        <h2 className="text-[15px] font-medium mb-3 text-mute">LOGS</h2>
        <pre className="surface-cloud p-4 text-xs font-mono overflow-x-auto whitespace-pre-wrap max-h-[28rem]">
          {logs.data?.logs || "// no log lines"}
        </pre>
      </section>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-mute mb-0.5">{label}</div>
      <div className="font-mono">{value}</div>
    </div>
  );
}
