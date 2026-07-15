# Build a container for the agent API and Discord bot.
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

# Default to the API server; docker-compose overrides this for the bot.
ENTRYPOINT ["uv", "run"]
CMD ["python", "-m", "agent", "api"]
