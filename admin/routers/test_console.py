"""POST /admin/test-console — trace a message through the pipeline.

Phase 1: dry_run=True always (admin IAM denies bedrock:* so vendor invocation
is impossible). The trace runs bouncer → classifier → strategist and returns
per-layer results with latencies.

The input must be already-redacted text. The test console never receives or
stores raw user input. Trace logs are emitted via safe_log (no message text).
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Request

from admin.models import TestConsoleLayerResult, TestConsoleRequest, TestConsoleResponse
from bouncer.bouncer import Bouncer
from bouncer.config import BouncerConfig
from classifier.classifier import Classifier
from classifier.config import ClassifierConfig
from shared.bedrock import BedrockRuntime
from shared.logging import safe_log
from shared.models import PipelineEnvelope
from strategist.config import StrategistConfig
from strategist.strategist import Strategist

router = APIRouter(prefix="/admin", tags=["test-console"])


def _make_envelope(req: TestConsoleRequest, correlation_id: str) -> PipelineEnvelope:
    import hashlib
    raw_hash = hashlib.sha256(req.redacted_message.encode()).hexdigest()
    return PipelineEnvelope(
        correlation_id=uuid.UUID(correlation_id),
        user_sub=req.user_sub,
        session_id=req.session_id,
        redacted_message=req.redacted_message,
        raw_message_hash=raw_hash,
        entity_types_redacted=(),
        entity_count=0,
        was_redacted=False,
        timestamp=datetime.now(UTC),
        bedrock_region="ap-southeast-1",
        source_ip="127.0.0.1",
    )


@router.post("/test-console", response_model=TestConsoleResponse)
async def test_console(body: TestConsoleRequest, request: Request) -> TestConsoleResponse:
    correlation_id = str(uuid.uuid4())
    layers: list[TestConsoleLayerResult] = []
    total_start = time.monotonic()
    final_vendor: str | None = None
    error: str | None = None

    safe_log.info(
        "admin.test_console.started",
        correlation_id=correlation_id,
        session_id=body.session_id,
    )

    try:
        envelope = _make_envelope(body, correlation_id)
        bedrock = BedrockRuntime()

        # --- Bouncer ---
        t0 = time.monotonic()
        try:
            # Use the admin's Redis connection; test console uses a distinct user_sub
            # so it won't interfere with production rate limit keys.
            redis_client: aioredis.Redis = aioredis.from_url(  # type: ignore[type-arg]
                request.app.state.config.redis_url
            )
            bouncer_cfg = BouncerConfig()
            bouncer = Bouncer(config=bouncer_cfg, redis=redis_client, bedrock=bedrock)
            bounce = await bouncer.bounce(envelope)
            layers.append(TestConsoleLayerResult(
                layer="bouncer",
                latency_ms=round((time.monotonic() - t0) * 1000, 1),
                outcome={
                    "allowed": bounce.allowed,
                    "reason": bounce.reason,
                    "layer": bounce.layer,
                    "confidence": bounce.confidence,
                    "escalate": bounce.escalate,
                    "timed_out": bounce.timed_out,
                },
            ))
            if not bounce.allowed:
                return _build_response(correlation_id, body.dry_run, layers, None, total_start, None)
        except Exception as exc:
            layers.append(TestConsoleLayerResult(
                layer="bouncer",
                latency_ms=round((time.monotonic() - t0) * 1000, 1),
                outcome={"error_type": type(exc).__name__},
            ))
            safe_log.warning("admin.test_console.bouncer_error", error_type=type(exc).__name__)
            bounce = None  # type: ignore[assignment]

        # --- Classifier ---
        t0 = time.monotonic()
        intent = None
        try:
            classifier_cfg = ClassifierConfig()
            classifier = Classifier(config=classifier_cfg, bedrock=bedrock)
            intent = await classifier.classify(envelope)
            layers.append(TestConsoleLayerResult(
                layer="classifier",
                latency_ms=round((time.monotonic() - t0) * 1000, 1),
                outcome={
                    "intent": intent.intent,
                    "domain": intent.domain,
                    "confidence": intent.confidence,
                    "path": intent.path,
                    "escalate": intent.escalate,
                },
            ))
        except Exception as exc:
            layers.append(TestConsoleLayerResult(
                layer="classifier",
                latency_ms=round((time.monotonic() - t0) * 1000, 1),
                outcome={"error_type": type(exc).__name__},
            ))
            safe_log.warning("admin.test_console.classifier_error", error_type=type(exc).__name__)

        # --- Strategist ---
        if intent is not None and not intent.escalate:
            t0 = time.monotonic()
            try:
                strategist_cfg = StrategistConfig()
                strategist = Strategist(config=strategist_cfg, bedrock=bedrock)
                plan = await strategist.route(envelope, intent)
                final_vendor = plan.primary_vendor if not plan.blocked else None
                layers.append(TestConsoleLayerResult(
                    layer="strategist",
                    latency_ms=round((time.monotonic() - t0) * 1000, 1),
                    outcome={
                        "primary_vendor": plan.primary_vendor,
                        "path": plan.path,
                        "blocked": plan.blocked,
                        "policy_modified": plan.policy_modified,
                        "applied_policies": list(plan.applied_policies),
                    },
                ))
            except Exception as exc:
                layers.append(TestConsoleLayerResult(
                    layer="strategist",
                    latency_ms=round((time.monotonic() - t0) * 1000, 1),
                    outcome={"error_type": type(exc).__name__},
                ))
                safe_log.warning("admin.test_console.strategist_error", error_type=type(exc).__name__)

        # Phase 1: always dry_run — vendor adapter not called (IAM denies bedrock:*)
        if not body.dry_run:
            layers.append(TestConsoleLayerResult(
                layer="adapter",
                latency_ms=0.0,
                outcome={"skipped": "vendor invocation disabled in Phase 1 admin context"},
            ))

    except Exception as exc:
        error = type(exc).__name__
        safe_log.warning("admin.test_console.error", error_type=type(exc).__name__)

    return _build_response(correlation_id, body.dry_run, layers, final_vendor, total_start, error)


def _build_response(
    correlation_id: str,
    dry_run: bool,
    layers: list[TestConsoleLayerResult],
    final_vendor: str | None,
    total_start: float,
    error: str | None,
) -> TestConsoleResponse:
    return TestConsoleResponse(
        correlation_id=correlation_id,
        dry_run=dry_run,
        layers=layers,
        final_vendor=final_vendor,
        total_latency_ms=round((time.monotonic() - total_start) * 1000, 1),
        error=error,
    )
