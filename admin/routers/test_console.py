"""POST /admin/test-console — send a message through the real pipeline via SQS.

Submits the raw message to the incoming SQS queue so the Orchestrator runs
the full pipeline: Presidio redaction → Bouncer → Classifier → Strategist →
Vendor adapter. Polls the DynamoDB audit table for the result by correlation_id,
then reconstructs a per-layer trace from the audit record.

Metrics impact: each trace increments real Bouncer/Classifier/Strategist
CloudWatch metrics.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

import aioboto3  # type: ignore[import-untyped]
from fastapi import APIRouter, Request

from admin.models import AuditRecord, TestConsoleLayerResult, TestConsoleRequest, TestConsoleResponse
from admin.services.dynamo_admin import DynamoAdminService
from shared.logging import safe_log

router = APIRouter(prefix="/admin/api", tags=["test-console"])

_POLL_INTERVAL_S: float = 2.0
_POLL_TIMEOUT_S: float = 30.0

_sqs_session: aioboto3.Session = aioboto3.Session()


async def _send_to_sqs(url: str, region: str, payload: dict[str, Any]) -> None:
    async with _sqs_session.client("sqs", region_name=region) as sqs:
        await sqs.send_message(QueueUrl=url, MessageBody=json.dumps(payload))


def _layer(name: str, outcome: dict[str, Any]) -> TestConsoleLayerResult:
    return TestConsoleLayerResult(layer=name, latency_ms=0.0, outcome=outcome)


def _layers_from_audit(record: AuditRecord) -> list[TestConsoleLayerResult]:
    """Reconstruct per-layer trace cards from an AuditRecord."""
    layers: list[TestConsoleLayerResult] = []

    # Redactor — always present (runs before any other layer)
    layers.append(_layer("redactor", {
        "was_redacted": record.was_redacted,
        "entity_count": record.entity_count,
        "entity_types": record.entity_types_redacted,
    }))

    # Bouncer
    if record.bouncer_allowed is not None:
        layers.append(_layer("bouncer", {
            "allowed": record.bouncer_allowed,
            "escalate": bool(record.bouncer_escalated),
            "timed_out": False,
        }))
        if not record.bouncer_allowed or record.bouncer_escalated:
            return layers

    # Classifier
    if record.intent is not None:
        layers.append(_layer("classifier", {
            "intent": record.intent,
            "confidence": record.intent_confidence,
            "escalate": bool(record.intent_escalated),
        }))
        if record.intent_escalated:
            return layers

    # Strategist
    if record.vendor is not None or record.routing_path is not None:
        layers.append(_layer("strategist", {
            "primary_vendor": record.vendor,
            "path": record.routing_path,
            "blocked": bool(record.policy_blocked),
        }))
        if record.policy_blocked:
            return layers

    # Adapter — only when a vendor actually responded
    if record.vendor is not None and not record.policy_blocked:
        layers.append(_layer("adapter", {"vendor": record.vendor}))

    return layers


@router.post("/test-console", response_model=TestConsoleResponse)
async def test_console(body: TestConsoleRequest, request: Request) -> TestConsoleResponse:
    cfg = request.app.state.config
    correlation_id = str(uuid.uuid4())
    total_start = time.monotonic()

    safe_log.info(
        "admin.test_console.started",
        correlation_id=correlation_id,
        session_id=body.session_id,
    )

    if not cfg.sqs_incoming_url:
        return TestConsoleResponse(
            correlation_id=correlation_id,
            layers=[],
            final_vendor=None,
            total_latency_ms=0.0,
            timed_out=False,
            error="SQSNotConfigured",
        )

    try:
        await _send_to_sqs(
            url=cfg.sqs_incoming_url,
            region=cfg.aws_region,
            payload={
                "message": body.message,
                "user_sub": body.user_sub,
                "session_id": body.session_id,
                "source_ip": "127.0.0.1",
                "correlation_id": correlation_id,
            },
        )
    except Exception as exc:
        safe_log.warning("admin.test_console.sqs_error", error_type=type(exc).__name__)
        return TestConsoleResponse(
            correlation_id=correlation_id,
            layers=[],
            final_vendor=None,
            total_latency_ms=round((time.monotonic() - total_start) * 1000, 1),
            timed_out=False,
            error=type(exc).__name__,
        )

    # Poll audit table until the Orchestrator writes the result
    dynamo: DynamoAdminService = request.app.state.dynamo
    deadline = time.monotonic() + _POLL_TIMEOUT_S
    audit_record = None

    while time.monotonic() < deadline:
        await asyncio.sleep(_POLL_INTERVAL_S)
        result = await dynamo.query_audit(correlation_id=correlation_id, limit=1)
        if result.records:
            audit_record = result.records[0]
            break

    total_ms = round((time.monotonic() - total_start) * 1000, 1)

    if audit_record is None:
        safe_log.warning("admin.test_console.timeout", correlation_id=correlation_id)
        return TestConsoleResponse(
            correlation_id=correlation_id,
            layers=[],
            final_vendor=None,
            total_latency_ms=total_ms,
            timed_out=True,
            error=None,
        )

    layers = _layers_from_audit(audit_record)
    final_vendor = audit_record.vendor if not audit_record.policy_blocked else None

    safe_log.info(
        "admin.test_console.completed",
        correlation_id=correlation_id,
        session_id=body.session_id,
    )

    return TestConsoleResponse(
        correlation_id=correlation_id,
        layers=layers,
        final_vendor=final_vendor,
        total_latency_ms=total_ms,
        timed_out=False,
        error=audit_record.error_type,
        response=audit_record.vendor_response_redacted,
    )
