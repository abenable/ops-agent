#!/usr/bin/env bash
# Combine the per-machine Prometheus + Loki extracts under data/aggregate/
# into one eval dataset: data/eval/combined_metrics.prom (OpenMetrics text,
# 5-minute resolution, machine="<host>" injected into every series), the same
# metrics as data/eval/combined_metrics.jsonl (one JSON object per sample), and
# data/eval/combined_logs.jsonl (one JSON object per log line).
#
# Requires: docker (prom/prometheus:latest and grafana/loki:latest images),
# python3. Run from the repo root. Safe to re-run; it overwrites its outputs.
set -euo pipefail
cd "$(dirname "$0")/.."

MACHINES=(marconi-01 marconi-02 lambda2)
STEP_SECONDS=300
WORK=data/eval/_work
LOG_START_NS=1787097600000000000  # 2026-08-19T00:00:00Z
LOG_END_NS=1787616000000000000    # 2026-08-25T00:00:00Z

rm -rf "$WORK"
mkdir -p "$WORK"
: > data/eval/combined_metrics.prom
: > data/eval/combined_logs.jsonl

for m in "${MACHINES[@]}"; do
  echo "== $m: metrics =="
  mkdir -p "$WORK/$m/prom"
  tar xf "data/aggregate/$m/prometheus-data.tar" -C "$WORK/$m/prom"
  chmod -R a+rwX "$WORK/$m/prom"
  docker run --rm --memory=3g -v "$(pwd)/$WORK/$m/prom:/prometheus" \
    --entrypoint promtool prom/prometheus:latest tsdb dump-openmetrics /prometheus \
    2> "$WORK/$m.prom.err" \
    | python3 scripts/downsample_openmetrics.py --machine "$m" --step-seconds "$STEP_SECONDS" \
    >> data/eval/combined_metrics.prom

  echo "== $m: logs =="
  mkdir -p "$WORK/$m/loki"
  tar xf "data/aggregate/$m/loki-data.tar" -C "$WORK/$m/loki"
  chmod -R a+rwX "$WORK/$m/loki"
  docker run -d --rm --name "loki-$m" --memory=1g \
    -v "$(pwd)/$WORK/$m/loki:/loki" \
    -v "$(pwd)/data/aggregate/$m/loki-config.yaml:/etc/loki/local-config.yaml:ro" \
    -P grafana/loki:latest -config.file=/etc/loki/local-config.yaml > /dev/null
  port=$(docker port "loki-$m" 3100/tcp | head -1 | cut -d: -f2)
  until curl -sf -m 2 "http://localhost:$port/ready" > /dev/null 2>&1; do sleep 2; done
  python3 scripts/dump_loki_logs.py --base-url "http://localhost:$port" --machine "$m" \
    --start-ns "$LOG_START_NS" --end-ns "$LOG_END_NS" \
    >> data/eval/combined_logs.jsonl 2> "$WORK/$m.loki.log"
  docker stop "loki-$m" > /dev/null

  # promtool and Loki write some files as their container's uid; a plain
  # `rm -rf` from the host user can't remove them.
  docker run --rm -v "$(pwd)/$WORK:/work" busybox rm -rf "/work/$m/prom" "/work/$m/loki"
done

# combined_metrics.jsonl is what agent.tools.helper reads; the .prom stays as
# the raw OpenMetrics form.
python3 scripts/metrics_to_jsonl.py \
  < data/eval/combined_metrics.prom > data/eval/combined_metrics.jsonl

echo "done:"
wc -l data/eval/combined_metrics.prom data/eval/combined_metrics.jsonl data/eval/combined_logs.jsonl
