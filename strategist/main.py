"""Strategist service — Phase 1: runs in-process within the orchestrator."""

from fastapi import FastAPI

app = FastAPI(title="strategist")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "strategist"}
