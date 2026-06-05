"""POST /admin/test-console — trace a pre-redacted message through the pipeline.

Runs Bouncer → Classifier → Strategist directly (no SQS, no vault, no Presidio).
Input must already be redacted; this endpoint traces routing decisions only.
dry_run=True (default): vendor adapter layer is omitted.
dry_run=False: an adapter layer is recorded as skipped.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Request

from admin.models import TestConsoleLayerResult, TestConsoleRequest, TestConsoleResponse
from bouncer.bouncer import Bouncer
from bouncer.config import BouncerConfig
from shared.bedrock import BedrockRuntime
from shared.logging import safe_log
from shared.models import PipelineEnvelope
from strategist.config import StrategistConfig
from strategist.strategist import Strategist

router = APIRouter(prefix="/admin", tags=["test-console"])


def _layer(name: str, start: float, outcome: dict[str, Any]) -> TestConsoleLayerResult:
    return TestConsoleLayerResult(
        layer=name,
        latency_ms=round((time.monotonic() - start) * 1000, 1),
        outcome=outcome,
    )


def _response(
    correlation_id: str,
    dry_run: bool,
    layers: list[TestConsoleLayerResult],
    final_vendor: str | None,
    total_start: float,
    error: str | None = None,
) -> TestConsoleResponse:
    return TestConsoleResponse(
        correlation_id=correlation_id,
        dry_run=dry_run,
        layers=layers,
        final_vendor=final_vendor,
        total_latency_ms=round((time.monotonic() - total_start) * 1000, 1),
        timed_out=False,
        error=error,
    )


@router.post("/test-console", response_model=TestConsoleResponse)
async def test_console(body: TestConsoleRequest, request: Request) -> TestConsoleResponse:
    correlation_id = str(uuid.uuid4())
    total_start = time.monotonic()
    layers: list[TestConsoleLayerResult] = []
    cfg = request.app.state.config

    # Build pipeline components (patched in tests via module-level names)
    bedrock = BedrockRuntime(region=cfg.aws_region)
    redis_client = aioredis.from_url(cfg.redis_url)
    bouncer = Bouncer(BouncerConfig(), redis_client, bedrock)
    classifier = request.app.state.classifier
    strategist = Strategist(StrategistConfig(), bedrock)

    envelope = PipelineEnvelope(
        correlation_id=uuid.UUID(correlation_id),
        user_sub=body.user_sub,
        session_id=body.session_id,
        redacted_message=body.redacted_message,
        raw_message_hash=hashlib.sha256(body.redacted_message.encode()).hexdigest(),
        entity_types_redacted=(),
        entity_count=0,
        was_redacted=False,
        timestamp=datetime.now(UTC),
        bedrock_region=cfg.aws_region,
        source_ip="127.0.0.1",
    )

    safe_log.info("admin.test_console.started", correlation_id=correlation_id)

    # ── Bouncer ────────────────────────────────────────────────────────────
    t0 = time.monotonic()
    try:
        bounce = await bouncer.bounce(envelope)
        layers.append(_layer("bouncer", t0, {
            "allowed": bounce.allowed,
            "escalate": bounce.escalate,
            "reason": bounce.reason,
            "confidence": bounce.confidence,
            "timed_out": bounce.timed_out,
        }))
        if not bounce.allowed or bounce.escalate:
            return _response(correlation_id, body.dry_run, layers, None, total_start)
    except Exception as exc:
        layers.append(_layer("bouncer", t0, {"error_type": type(exc).__name__}))
        return _response(correlation_id, body.dry_run, layers, None, total_start,
                         error=type(exc).__name__)

    # ── Classifier ─────────────────────────────────────────────────────────
    t0 = time.monotonic()
    try:
        intent = await classifier.classify(envelope)
        layers.append(_layer("classifier", t0, {
            "intent": intent.intent,
            "confidence": intent.confidence,
            "escalate": intent.escalate,
            "path": str(intent.path),
        }))
        if intent.escalate:
            return _response(correlation_id, body.dry_run, layers, None, total_start)
    except Exception as exc:
        layers.append(_layer("classifier", t0, {"error_type": type(exc).__name__}))
        return _response(correlation_id, body.dry_run, layers, None, total_start,
                         error=type(exc).__name__)

    # ── Strategist ─────────────────────────────────────────────────────────
    t0 = time.monotonic()
    try:
        plan = await strategist.route(envelope, intent)
        layers.append(_layer("strategist", t0, {
            "primary_vendor": plan.primary_vendor,
            "path": str(plan.path),
            "blocked": plan.blocked,
            "policy_modified": plan.policy_modified,
            "applied_policies": list(plan.applied_policies),
        }))
        final_vendor = None if plan.blocked else plan.primary_vendor
    except Exception as exc:
        layers.append(_layer("strategist", t0, {"error_type": type(exc).__name__}))
        return _response(correlation_id, body.dry_run, layers, None, total_start,
                         error=type(exc).__name__)

    # ── Adapter (always skipped in test console) ───────────────────────────
    if not body.dry_run:
        layers.append(TestConsoleLayerResult(
            layer="adapter",
            latency_ms=0.0,
            outcome={"skipped": True},
        ))

    safe_log.info("admin.test_console.completed", correlation_id=correlation_id)
    return _response(correlation_id, body.dry_run, layers, final_vendor, total_start)
