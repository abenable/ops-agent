# Build the Vite SPA with bun, serve the static bundle with nginx.
# nginx proxies /api/ to the api container over the shared host network
# (loopback), so the browser stays same-origin and no API key / CORS is needed.
FROM oven/bun:1 AS build
WORKDIR /app

COPY package.json bun.lock ./
RUN bun install

COPY . .
RUN bun run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8088
