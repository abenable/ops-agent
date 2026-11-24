FROM python:3.13-slim-bookworm

WORKDIR /app

# ssh: NODES reaches other machines' Docker over SSH (docker system dial-stdio).
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

# Dependencies install before the source is copied, so editing code reuses this layer.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev

ENTRYPOINT ["uv", "run"]
CMD ["python", "-m", "agent", "bot"]
