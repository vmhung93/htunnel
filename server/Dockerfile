# htunnel relay server
# Build:  docker build -t <dockerhub-user>/htunnel:latest server
# Run:    docker run --rm -p 10000:10000 -e CHANNEL_TOKENS="user1=<token>" <dockerhub-user>/htunnel

# --- Build stage: resolve dependencies from uv.lock into a virtualenv ---
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.10.11 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Dependencies first, so code changes don't invalidate this layer
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY . .

# --- Runtime stage: just Python, the virtualenv and the code ---
FROM python:3.12-slim

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PORT=10000

RUN useradd --system --uid 10001 --no-create-home htunnel

WORKDIR /app
COPY --from=builder --chown=htunnel:htunnel /app /app

USER htunnel

EXPOSE 10000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"10000\")}/health', timeout=3)"

# server.py reads PORT and sets the graceful-shutdown timeout that SSE streams need.
# Exec form, so uvicorn receives SIGTERM directly from `docker stop` / Render.
CMD ["python", "server.py"]
