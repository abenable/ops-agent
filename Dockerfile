# The bot image: Python agent only (no web dashboard).
FROM python:3.13-slim-bookworm

WORKDIR /app

# Install uv.
RUN pip install --no-cache-dir uv

# Copy project metadata and install dependencies first (cached layer).
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy source after dependencies are installed.
COPY src ./src
RUN uv sync --frozen --no-dev

# Default to the Discord bot.
ENTRYPOINT ["uv", "run"]
CMD ["python", "-m", "agent", "bot"]
