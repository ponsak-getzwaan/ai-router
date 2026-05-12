"""Admin dashboard — read-heavy; write surfaces: routing rules, escalation queue, tier overrides.

Phase 1: minimal health endpoint. Full dashboard is a separate task.
"""

from fastapi import FastAPI

app = FastAPI(title="admin")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "admin"}
