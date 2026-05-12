"""Bouncer service — Phase 1: runs in-process within the orchestrator.

This FastAPI app is the ECS healthcheck target. The actual bouncer logic
is imported directly by the orchestrator pipeline driver.
"""

from fastapi import FastAPI

app = FastAPI(title="bouncer")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "bouncer"}
