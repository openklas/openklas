# syntax=docker/dockerfile:1.7
# ─────────────────────────────────────────────────────────────────────────────
# OpenKLAS backend
#
# Base image: Microsoft's official Playwright-for-Python image — ships with
# Chromium + system deps so headless browser flows (watch / summarize) work
# without an apt-install dance. ffmpeg is added on top for audio extraction.
# ─────────────────────────────────────────────────────────────────────────────
FROM mcr.microsoft.com/playwright/python:v1.59.0-jammy

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:/root/.local/bin:$PATH

# System packages: ffmpeg for audio extraction, curl for healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv (used as the sole dep manager — pyproject.toml + uv.lock authoritative)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

WORKDIR /app

# ── Dependency layer (cached) ────────────────────────────────────────────────
# Copy ONLY the manifest first so the heavy `uv sync` step is cached across
# code-only rebuilds.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ── App layer ────────────────────────────────────────────────────────────────
COPY . .
RUN uv sync --frozen --no-dev

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Single worker by default; scale horizontally via `docker compose --scale api=N`
# (sessions live in Redis, so workers can share state).
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
