"""Shared fixtures for admin dashboard tests.

Strategy: ASGITransport does not send ASGI lifespan events, so app.state is
injected directly before the client is created rather than relying on the
lifespan. All four service objects are MagicMocks with AsyncMock methods
configured to sensible defaults; individual tests override only what they test.

State key mapping (matches admin/main.py lifespan):
  app.state.cloudwatch → AdminCtx.cloudwatch
  app.state.dynamo     → AdminCtx.dynamo
  app.state.sqs_admin  → AdminCtx.sqs
  app.state.redis      → AdminCtx.redis
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from admin.config import AdminConfig
from admin.main import app as admin_app
from admin.models import (
    AuditQuery,
    AuditRecord,
    BouncerMetrics,
    ClassifierMetrics,
    EscalationAction,
    EscalationList,
    EscalationMessage,
    LatencyPercentiles,
    PipelineMetrics,
    RedactionMetrics,
    RoutingRule,
)


# ---------------------------------------------------------------------------
# Default responses — realistic but empty enough to not influence assertions
# ---------------------------------------------------------------------------

def make_pipeline_metrics(period: int = 60) -> PipelineMetrics:
    return PipelineMetrics(
        period_minutes=period,
        total_requests=100.0,
        error_rate_pct=1.5,
        escalation_rate_pct=5.0,
        latency_ms=LatencyPercentiles(p50=45.0, p99=200.0, p999=None),
    )


def make_bouncer_metrics(period: int = 60) -> BouncerMetrics:
    return BouncerMetrics(
        period_minutes=period,
        total=100.0,
        passed=85.0,
        rejected=10.0,
        escalated=5.0,
        timed_out=1.0,
        errors=0.0,
        pass_rate_pct=85.0,
        avg_confidence=0.88,
    )


def make_classifier_metrics(period: int = 60) -> ClassifierMetrics:
    return ClassifierMetrics(
        period_minutes=period,
        total=85.0,
        fast_path=60.0,
        deep_path=25.0,
        escalated=5.0,
        intent_counts={"general_qa": 40.0, "code_assistance": 30.0},
    )


def make_redaction_metrics(period: int = 60) -> RedactionMetrics:
    return RedactionMetrics(
        period_minutes=period,
        total_processed=100.0,
        total_entities_redacted=15.0,
        entity_type_counts={"SG_NRIC": 10.0, "CREDIT_CARD": 5.0},
    )


def make_routing_rule(intent: str = "general_qa") -> RoutingRule:
    return RoutingRule(
        intent=intent,
        vendor="apac.anthropic.claude-sonnet-4-6-20241022-v2:0",
        fallback="apac.anthropic.claude-haiku-4-5-20241022-v1:0",
        description="General questions",
    )


def make_audit_record(cid: str = "test-cid-001") -> AuditRecord:
    return AuditRecord(
        correlation_id=cid,
        timestamp=datetime.now(UTC).isoformat(),
        user_sub="user-sub-123",
        session_id="session-abc",
        entity_types_redacted=["SG_NRIC"],
        entity_count=1,
        was_redacted=True,
        bouncer_allowed=True,
        bouncer_escalated=False,
        intent="general_qa",
        intent_confidence="0.92",
        vendor="apac.anthropic.claude-sonnet-4-6-20241022-v2:0",
        routing_path="deterministic",
        policy_blocked=False,
        total_latency_ms="342.5",
        error_type=None,
    )


def make_escalation_message(cid: str = "esc-cid-001") -> EscalationMessage:
    return EscalationMessage(
        receipt_handle="receipt-handle-abc",
        message_id="msg-id-123",
        correlation_id=cid,
        user_sub="user-sub-456",
        session_id="session-xyz",
        redacted_preview="What is the status of VAULT_3A4B5C?",  # redacted, not raw
        entity_types=["SG_NRIC"],
        bouncer_reason="low_confidence",
        sent_at=datetime.now(UTC),
        approximate_receive_count=1,
    )


# ---------------------------------------------------------------------------
# Main test context
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class AdminCtx:
    client: AsyncClient
    cloudwatch: MagicMock
    dynamo: MagicMock
    sqs: MagicMock
    redis: MagicMock


@pytest.fixture
async def ctx() -> AdminCtx:  # type: ignore[misc]
    """Admin test client with all services injected directly into app.state.

    ASGITransport does not send ASGI lifespan startup/shutdown events, so we
    bypass the lifespan entirely and populate app.state ourselves.
    """
    mock_redis = MagicMock()
    mock_redis.connect = AsyncMock()
    mock_redis.close = AsyncMock()
    mock_redis.health = AsyncMock(return_value="ok")
    mock_redis.stats = AsyncMock(return_value={"active_vault_keys": 3})

    mock_cw = MagicMock()
    mock_cw.pipeline_metrics = AsyncMock(return_value=make_pipeline_metrics())
    mock_cw.bouncer_metrics = AsyncMock(return_value=make_bouncer_metrics())
    mock_cw.classifier_metrics = AsyncMock(return_value=make_classifier_metrics())
    mock_cw.redaction_metrics = AsyncMock(return_value=make_redaction_metrics())

    mock_dynamo = MagicMock()
    mock_dynamo.list_routing_rules = AsyncMock(return_value=[make_routing_rule()])
    mock_dynamo.get_routing_rule = AsyncMock(return_value=make_routing_rule())
    mock_dynamo.put_routing_rule = AsyncMock(return_value=make_routing_rule())
    mock_dynamo.query_audit = AsyncMock(
        return_value=AuditQuery(records=[make_audit_record()], count=1, last_evaluated_key=None)
    )

    mock_sqs = MagicMock()
    mock_sqs.list_pending = AsyncMock(
        return_value=EscalationList(messages=[make_escalation_message()], queue_depth=1)
    )
    mock_sqs.approve = AsyncMock(
        return_value=EscalationAction(
            message_id="", action="approved", correlation_id="esc-cid-001", annotation=None
        )
    )
    mock_sqs.reject = AsyncMock(
        return_value=EscalationAction(
            message_id="", action="rejected", correlation_id="esc-cid-001", annotation=None
        )
    )
    mock_sqs.requeue = AsyncMock(
        return_value=EscalationAction(
            message_id="", action="requeued", correlation_id="esc-cid-001", annotation="needs review"
        )
    )

    # Populate app.state directly — bypasses lifespan
    admin_app.state.config = AdminConfig()
    admin_app.state.cloudwatch = mock_cw
    admin_app.state.dynamo = mock_dynamo
    admin_app.state.sqs_admin = mock_sqs
    admin_app.state.redis = mock_redis

    async with AsyncClient(
        transport=ASGITransport(app=admin_app),
        base_url="http://test",
    ) as client:
        yield AdminCtx(
            client=client,
            cloudwatch=mock_cw,
            dynamo=mock_dynamo,
            sqs=mock_sqs,
            redis=mock_redis,
        )

    # Clean up state to prevent bleed between tests
    for attr in ("config", "cloudwatch", "dynamo", "sqs_admin", "redis"):
        try:
            delattr(admin_app.state, attr)
        except AttributeError:
            pass
