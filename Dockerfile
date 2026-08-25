FROM python:3.13-slim-bookworm

WORKDIR /app

RUN pip install --no-cache-dir uv

# Dependencies install before the source is copied, so editing code reuses this layer.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev

ENTRYPOINT ["uv", "run"]
CMD ["python", "-m", "agent", "bot"]
