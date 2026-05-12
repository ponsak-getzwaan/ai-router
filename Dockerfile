# Base image for all pipeline services (orchestrator, bouncer, classifier, etc.)
# Build arg SERVICE selects which uvicorn entrypoint to use.
#
# Build:  docker build --build-arg SERVICE=orchestrator -t ai-router/orchestrator .
# Run:    docker run -e ORCHESTRATOR_SQS_INCOMING_URL=... ai-router/orchestrator

ARG SERVICE=orchestrator

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_NO_CACHE=1 \
    PATH="/app/.venv/bin:$PATH"

RUN pip install --no-cache-dir uv

WORKDIR /app

# Install dependencies first (layer caches unless pyproject.toml changes)
COPY pyproject.toml README.md ./
RUN uv sync --no-dev

# Copy application source
COPY shared/ ./shared/
COPY bouncer/ ./bouncer/
COPY classifier/ ./classifier/
COPY strategist/ ./strategist/
COPY adapters/ ./adapters/
COPY orchestrator/ ./orchestrator/
COPY admin/ ./admin/

ARG SERVICE
ENV SERVICE=${SERVICE}

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD uvicorn ${SERVICE}.main:app --host 0.0.0.0 --port 8000
