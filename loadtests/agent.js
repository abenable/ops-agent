// k6 load-testing script for the ops-agent API.
//
// Usage:
//   k6 run loadtests/agent.js
//
// Or with custom settings:
//   k6 run --vus 20 --duration 60s loadtests/agent.js
//
// You can override the base URL via the API_BASE environment variable:
//   k6 run -e API_BASE=http://localhost:8123 loadtests/agent.js

import http from "k6/http";
import { check, sleep, group } from "k6";

const BASE = __ENV.API_BASE || "http://localhost:8123";

export const options = {
  stages: [
    { duration: "10s", target: 5 },   // ramp up
    { duration: "30s", target: 20 },  // hold at steady load
    { duration: "10s", target: 0 },   // ramp down
  ],
  thresholds: {
    "http_req_duration{name:health}": ["p(95)<200"],
    "http_req_duration{name:status}": ["p(95)<500"],
    "http_req_duration{name:containers}": ["p(95)<1000"],
    "http_req_duration{name:incidents}": ["p(95)<200"],
    "http_req_duration{name:metrics}": ["p(95)<200"],
  },
};

// Sample container names for status lookups.
const SERVICES = ["app", "api", "web", "postgres", "worker", "ingress"];

export default function () {
  group("health check", () => {
    const res = http.get(`${BASE}/health`, { tags: { name: "health" } });
    check(res, { "status 200": (r) => r.status === 200 });
    sleep(0.1);
  });

  group("metrics endpoint", () => {
    const res = http.get(`${BASE}/metrics`, { tags: { name: "metrics" } });
    check(res, {
      "status 200": (r) => r.status === 200,
      "is text/plain": (r) => r.headers["Content-Type"]?.startsWith("text/plain"),
    });
    sleep(0.2);
  });

  group("service status", () => {
    const svc = SERVICES[Math.floor(Math.random() * SERVICES.length)];
    const res = http.get(`${BASE}/services/${svc}/status`, { tags: { name: "status" } });
    check(res, { "status ok": (r) => r.status === 200 });
    sleep(0.3);
  });

  group("container list", () => {
    const res = http.get(`${BASE}/containers`, { tags: { name: "containers" } });
    check(res, { "status ok": (r) => r.status === 200 });
    sleep(0.3);
  });

  group("incident list", () => {
    const res = http.get(`${BASE}/incidents`, { tags: { name: "incidents" } });
    check(res, { "status ok": (r) => r.status === 200 });
    sleep(0.2);
  });
}

export function teardown() {
  // Report final agent metrics from /metrics
  const metrics = http.get(`${BASE}/metrics`);
  console.log("--- Final agent metrics ---");
  console.log(metrics.body);
}
