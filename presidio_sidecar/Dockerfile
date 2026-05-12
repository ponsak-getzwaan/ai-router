# Presidio sidecar — separate image because the spaCy model is ~200MB
# and must not be bundled into the orchestrator image.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_NO_CACHE=1 \
    PATH="/app/.venv/bin:$PATH"

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml README.md ./
RUN uv sync --no-dev --extra presidio

# Download the spaCy English model at build time so it's baked into the image.
# This means the ~200MB model is never downloaded at runtime (cold start safety).
RUN uv run python -m spacy download en_core_web_sm

COPY presidio_sidecar/ ./presidio_sidecar/

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

CMD uvicorn presidio_sidecar.main:app --host 0.0.0.0 --port 8080
