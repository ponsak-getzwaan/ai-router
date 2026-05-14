"""Unit tests for orchestrator.audit.AuditLogger.

DynamoDB session chain is fully mocked — no real AWS calls.
asyncio_mode=auto means no @pytest.mark.asyncio needed.
"""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from orchestrator.audit import AuditLogger
from shared.models import (
    BounceResult,
    BouncerLayer,
    ClassifiedIntent,
    ClassifierPath,
    EntityType,
    IntentDomain,
    PipelineEnvelope,
    RoutingContext,
    RoutingPlan,
    StrategistPath,
)

# =============================================================================
# Helpers / fixtures
# =============================================================================


def make_envelope(
    message: str = "Hello world",
    entity_types: tuple[EntityType, ...] = (),
    entity_count: int = 0,
    was_redacted: bool = False,
) -> PipelineEnvelope:
    raw_hash = hashlib.sha256(message.encode()).hexdigest()
    return PipelineEnvelope(
        correlation_id=uuid4(),
        user_sub="user-sub-xyz",
        session_id="session-id-abc",
        redacted_message=message,
        raw_message_hash=raw_hash,
        entity_types_redacted=entity_types,
        entity_count=entity_count,
        was_redacted=was_redacted,
        timestamp=datetime.now(UTC),
        bedrock_region="ap-southeast-1",
        source_ip="1.2.3.4",
    )


def make_bounce(allowed: bool = True) -> BounceResult:
    return BounceResult(
        allowed=allowed,
        reason="safe",
        layer=BouncerLayer.LLM_CLASSIFIER,
        confidence=0.9,
    )


def make_intent(escalate: bool = False) -> ClassifiedIntent:
    return ClassifiedIntent(
        intent="general_qa",
        domain=IntentDomain.GENERAL_QA,
        confidence=0.88,
        resolved_message="Hello world",
        path=ClassifierPath.FAST,
        escalate=escalate,
    )


def make_plan(blocked: bool = False) -> RoutingPlan:
    return RoutingPlan(
        primary_vendor="apac.anthropic.claude-sonnet-4-6-20241022-v2:0",
        fallback_chain=(),
        context=RoutingContext(timeout_seconds=10.0, max_retries=2, streaming=False),
        path=StrategistPath.DETERMINISTIC,
        blocked=blocked,
    )


def make_mock_session() -> tuple[MagicMock, AsyncMock, AsyncMock]:
    """Return (mock_session, mock_dynamo, mock_table)."""
    mock_table = AsyncMock()
    mock_dynamo = AsyncMock()
    mock_dynamo.Table = AsyncMock(return_value=mock_table)

    mock_session = MagicMock()
    mock_resource_ctx = MagicMock()
    mock_resource_ctx.__aenter__ = AsyncMock(return_value=mock_dynamo)
    mock_resource_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_session.resource.return_value = mock_resource_ctx

    return mock_session, mock_dynamo, mock_table


def make_logger() -> AuditLogger:
    return AuditLogger(table_name="ai-router-audit", region="ap-southeast-1")


# =============================================================================
# Tests
# =============================================================================


async def test_writes_correlation_id() -> None:
    envelope = make_envelope()
    mock_session, _, mock_table = make_mock_session()

    with patch("orchestrator.audit.aioboto3.Session", return_value=mock_session):
        logger = make_logger()
        await logger.write(
            envelope=envelope,
            bounce=make_bounce(),
            intent=make_intent(),
            plan=make_plan(),
            vendor_response="some response",
            start_time=time.monotonic(),
        )

    mock_table.put_item.assert_called_once()
    item = mock_table.put_item.call_args.kwargs["Item"]
    assert item["correlation_id"] == str(envelope.correlation_id)


async def test_writes_entity_types_not_values() -> None:
    """Item must contain entity type names, never PII values."""
    envelope = make_envelope(
        entity_types=(EntityType.SG_NRIC, EntityType.CREDIT_CARD),
        entity_count=2,
        was_redacted=True,
    )
    mock_session, _, mock_table = make_mock_session()

    with patch("orchestrator.audit.aioboto3.Session", return_value=mock_session):
        logger = make_logger()
        await logger.write(
            envelope=envelope,
            bounce=make_bounce(),
            intent=make_intent(),
            plan=make_plan(),
            vendor_response=None,
            start_time=time.monotonic(),
        )

    item = mock_table.put_item.call_args.kwargs["Item"]
    entity_types_in_item = item["entity_types_redacted"]
    # Must be a list of type names (strings), not actual values
    assert "SG_NRIC" in entity_types_in_item
    assert "CREDIT_CARD" in entity_types_in_item


async def test_no_message_in_audit_item() -> None:
    """The audit item must never carry message content."""
    envelope = make_envelope(message="very sensitive user message")
    mock_session, _, mock_table = make_mock_session()

    with patch("orchestrator.audit.aioboto3.Session", return_value=mock_session):
        logger = make_logger()
        await logger.write(
            envelope=envelope,
            bounce=make_bounce(),
            intent=make_intent(),
            plan=make_plan(),
            vendor_response="vendor said hi",
            start_time=time.monotonic(),
        )

    item = mock_table.put_item.call_args.kwargs["Item"]
    forbidden_keys = {"message", "raw_message", "redacted_message", "content", "prompt"}
    assert forbidden_keys.isdisjoint(set(item.keys())), (
        f"Forbidden keys found in audit item: {forbidden_keys & set(item.keys())}"
    )


async def test_none_values_excluded_from_item() -> None:
    """DynamoDB doesn't accept None — those keys must be stripped."""
    envelope = make_envelope()
    mock_session, _, mock_table = make_mock_session()

    with patch("orchestrator.audit.aioboto3.Session", return_value=mock_session):
        logger = make_logger()
        # Pass None for bounce, intent, plan
        await logger.write(
            envelope=envelope,
            bounce=None,
            intent=None,
            plan=None,
            vendor_response=None,
            start_time=time.monotonic(),
        )

    item = mock_table.put_item.call_args.kwargs["Item"]
    # No value in item should be None
    assert all(v is not None for v in item.values()), (
        "None values found in audit item — DynamoDB would reject this"
    )


async def test_writes_vendor_when_plan_available() -> None:
    envelope = make_envelope()
    plan = make_plan()
    mock_session, _, mock_table = make_mock_session()

    with patch("orchestrator.audit.aioboto3.Session", return_value=mock_session):
        logger = make_logger()
        await logger.write(
            envelope=envelope,
            bounce=make_bounce(),
            intent=make_intent(),
            plan=plan,
            vendor_response="ok",
            start_time=time.monotonic(),
        )

    item = mock_table.put_item.call_args.kwargs["Item"]
    assert item["vendor"] == plan.primary_vendor


async def test_writes_error_type_on_failure() -> None:
    envelope = make_envelope()
    mock_session, _, mock_table = make_mock_session()

    with patch("orchestrator.audit.aioboto3.Session", return_value=mock_session):
        logger = make_logger()
        await logger.write(
            envelope=envelope,
            bounce=None,
            intent=None,
            plan=None,
            vendor_response=None,
            start_time=time.monotonic(),
            error_type="BedrockError",
        )

    item = mock_table.put_item.call_args.kwargs["Item"]
    assert item["error_type"] == "BedrockError"


async def test_dynamo_error_does_not_raise() -> None:
    """Best-effort audit: DynamoDB failures must not propagate."""
    envelope = make_envelope()
    mock_session, _, mock_table = make_mock_session()
    mock_table.put_item = AsyncMock(side_effect=Exception("DynamoDB unavailable"))

    with patch("orchestrator.audit.aioboto3.Session", return_value=mock_session):
        logger = make_logger()
        # Must not raise
        await logger.write(
            envelope=envelope,
            bounce=make_bounce(),
            intent=make_intent(),
            plan=make_plan(),
            vendor_response=None,
            start_time=time.monotonic(),
        )


async def test_ttl_is_set() -> None:
    """Audit record TTL must be an integer (365 days from now)."""
    envelope = make_envelope()
    mock_session, _, mock_table = make_mock_session()
    now = int(time.time())

    with patch("orchestrator.audit.aioboto3.Session", return_value=mock_session):
        logger = make_logger()
        await logger.write(
            envelope=envelope,
            bounce=make_bounce(),
            intent=make_intent(),
            plan=make_plan(),
            vendor_response=None,
            start_time=time.monotonic(),
        )

    item = mock_table.put_item.call_args.kwargs["Item"]
    assert "ttl" in item
    ttl = item["ttl"]
    assert isinstance(ttl, int)
    # TTL should be approximately 365 days from now (within a 60s margin)
    expected = now + 365 * 86400
    assert abs(ttl - expected) < 60
