"""POST /admin/test-console — trace a pre-redacted message through the pipeline.

Runs Bouncer → Classifier → Strategist directly (no SQS, no vault, no Presidio).
Input must already be redacted; this endpoint traces routing decisions only.
dry_run=True: stop after Strategist, return routing trace only.
dry_run=False (default): also invoke the vendor adapter (non-streaming only —
admin IAM denies bedrock:InvokeModelWithResponseStream) and return the response.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import aioboto3  # type: ignore[import-untyped]
import redis.asyncio as aioredis
from fastapi import APIRouter, Request

from adapters.litellm_adapter import invoke as litellm_invoke
from admin.models import TestConsoleLayerResult, TestConsoleRequest, TestConsoleResponse
from bouncer.bouncer import Bouncer
from bouncer.config import BouncerConfig
from orchestrator.history import SessionHistory
from shared.logging import safe_log
from shared.models import PipelineEnvelope
from strategist.config import StrategistConfig
from strategist.strategist import Strategist

router = APIRouter(prefix="/admin", tags=["test-console"])

_sqs_session: aioboto3.Session = aioboto3.Session()


async def _enqueue_escalation(
    cfg: Any,
    envelope: PipelineEnvelope,
    correlation_id: str,
    bouncer_reason: str | None,
) -> None:
    """Send escalated message to the SQS escalation queue (best-effort, never raises)."""
    if not cfg.sqs_escalation_url:
        return
    try:
        msg = {
            "correlation_id": correlation_id,
            "user_sub": envelope.user_sub,
            "session_id": envelope.session_id,
            "redacted_message": envelope.redacted_message,
            "entity_types": [t.value for t in envelope.entity_types_redacted],
            "bouncer_reason": bouncer_reason,
            "source": "test_console",
        }
        async with _sqs_session.client("sqs", region_name=cfg.aws_region) as sqs:
            await sqs.send_message(
                QueueUrl=cfg.sqs_escalation_url,
                MessageBody=json.dumps(msg),
            )
        safe_log.info("admin.test_console.escalation_queued", correlation_id=correlation_id)
    except Exception as exc:
        safe_log.warning("admin.test_console.escalation_queue_error", error_type=type(exc).__name__)


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
    response: str | None = None,
) -> TestConsoleResponse:
    return TestConsoleResponse(
        correlation_id=correlation_id,
        dry_run=dry_run,
        layers=layers,
        final_vendor=final_vendor,
        total_latency_ms=round((time.monotonic() - total_start) * 1000, 1),
        timed_out=False,
        error=error,
        response=response,
    )


@router.post("/test-console", response_model=TestConsoleResponse)
async def test_console(body: TestConsoleRequest, request: Request) -> TestConsoleResponse:
    correlation_id = str(uuid.uuid4())
    total_start = time.monotonic()
    layers: list[TestConsoleLayerResult] = []
    cfg = request.app.state.config

    # Reuse the startup BedrockRuntime — shares the HTTP connection pool across
    # requests so the bouncer Haiku call gets a warm connection, not a cold TLS start.
    bedrock = request.app.state.bedrock
    redis_client = aioredis.from_url(cfg.redis_url)
    bouncer = Bouncer(BouncerConfig(), redis_client, bedrock)
    session_history = SessionHistory(redis_client)
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
            if bounce.escalate:
                await _enqueue_escalation(cfg, envelope, correlation_id, bounce.reason)
            return _response(correlation_id, body.dry_run, layers, None, total_start)
    except Exception as exc:
        layers.append(_layer("bouncer", t0, {"error_type": type(exc).__name__}))
        return _response(correlation_id, body.dry_run, layers, None, total_start,
                         error=type(exc).__name__)

    # ── Classifier ─────────────────────────────────────────────────────────
    history = await session_history.get(body.session_id)
    t0 = time.monotonic()
    try:
        intent = await classifier.classify(envelope, history=history)
        layers.append(_layer("classifier", t0, {
            "intent": intent.intent,
            "confidence": intent.confidence,
            "escalate": intent.escalate,
            "path": str(intent.path),
        }))
        if intent.escalate:
            await _enqueue_escalation(cfg, envelope, correlation_id, bouncer_reason=None)
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

    # ── Adapter ────────────────────────────────────────────────────────────
    vendor_response: str | None = None
    if not body.dry_run and final_vendor:
        # Admin IAM denies bedrock:InvokeModelWithResponseStream — force non-streaming.
        non_streaming_context = plan.context.model_copy(update={"streaming": False})
        non_streaming_plan = plan.model_copy(update={"context": non_streaming_context})
        t0 = time.monotonic()
        try:
            vendor_response = await litellm_invoke(envelope, non_streaming_plan)
            layers.append(_layer("adapter", t0, {"vendor": final_vendor}))
            if vendor_response:
                await session_history.append(body.session_id, body.redacted_message, vendor_response)
        except Exception as exc:
            layers.append(_layer("adapter", t0, {"error_type": type(exc).__name__}))

    safe_log.info("admin.test_console.completed", correlation_id=correlation_id)
    return _response(correlation_id, body.dry_run, layers, final_vendor, total_start,
                     response=vendor_response)
