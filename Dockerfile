# Build the API/bot image with the SPA web dashboard baked in.
# Stage 1: build the Vite SPA with bun.
FROM oven/bun:1 AS spa

WORKDIR /app
COPY web/package.json web/bun.lock ./
RUN bun install
COPY web/ ./
RUN bun run build

# Stage 2: the Python agent.
FROM python:3.13-slim-bookworm

WORKDIR /app

# Install uv.
RUN pip install --no-cache-dir uv

# Copy project metadata and install dependencies first (cached layer).
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy source and scenarios after dependencies are installed.
COPY src ./src
COPY scenarios ./scenarios
RUN uv sync --frozen --no-dev

# Copy the built SPA so the API's StaticFiles mount picks it up at /.
COPY --from=spa /app/dist /app/web/dist

# Default to the API server; docker-compose overrides this for the bot.
ENTRYPOINT ["uv", "run"]
CMD ["python", "-m", "agent", "api"]
