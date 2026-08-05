# Build the Vite SPA with bun. nginx is gone — Caddy (host systemd service)
# serves the bundle and reverse-proxies /api/* to the API on 127.0.0.1:8123.
# This image is a build-only step: compose copies /app/dist to the Caddy web
# root host directory, then the container exits.
FROM oven/bun:1 AS build
WORKDIR /app

COPY package.json bun.lock ./
RUN bun install

COPY . .
RUN bun run build
