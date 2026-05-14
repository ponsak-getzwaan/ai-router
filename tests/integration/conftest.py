"""Shared fixtures for integration tests.

Integration tests use:
- fakeredis for Redis/vault (real data structure, no network)
- moto for SQS/DynamoDB (real AWS API surface, no network)
- AsyncMock for PresidioClient and LiteLLM vendor adapter (external HTTP/Bedrock)
- Real Bouncer/Classifier/Strategist interfaces via mock objects
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import fakeredis.aioredis
import pytest

from orchestrator.audit import AuditLogger
from orchestrator.pipeline_driver import PipelineDriver
from orchestrator.presidio_client import PresidioClient
from shared.models import (
    BounceResult,
    BouncerLayer,
    ClassifiedIntent,
    ClassifierPath,
    EntityType,
    IntentDomain,
    RedactionResult,
    RoutingContext,
    RoutingPlan,
    StrategistPath,
)

REGION = "ap-southeast-1"
AUDIT_TABLE = "ai-router-audit"
INCOMING_QUEUE = "ai-router-incoming"

# Fixed UUID used in RedactionResult so fixtures don't need to coordinate
_FIXED_CID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


@pytest.fixture(autouse=True)
def aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject fake AWS credentials required by moto."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)


@pytest.fixture
async def redis_client():
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


# ---------------------------------------------------------------------------
# Default model builders
# ---------------------------------------------------------------------------

def make_redaction_result(
    redacted: str = "What is VAULT_3A4B5C status?",
    was_redacted: bool = True,
) -> RedactionResult:
    return RedactionResult(
        redacted_message=redacted,
        entity_types_found=(EntityType.SG_NRIC,) if was_redacted else (),
        entity_count=1 if was_redacted else 0,
        was_redacted=was_redacted,
        correlation_id=_FIXED_CID,
    )


def make_bounce_result(
    allowed: bool = True,
    reason: str = "passed",
    escalate: bool = False,
    timed_out: bool = False,
) -> BounceResult:
    return BounceResult(
        allowed=allowed,
        reason=reason,
        layer=BouncerLayer.RULE_GATE,
        confidence=0.95,
        escalate=escalate,
        timed_out=timed_out,
    )


def make_intent_result(escalate: bool = False, intent: str = "general_qa") -> ClassifiedIntent:
    return ClassifiedIntent(
        intent=intent,
        domain=IntentDomain.GENERAL_QA,
        confidence=0.92,
        path=ClassifierPath.FAST,
        resolved_message="What is VAULT_3A4B5C status?",
        escalate=escalate,
    )


def make_routing_plan(blocked: bool = False) -> RoutingPlan:
    return RoutingPlan(
        primary_vendor="apac.anthropic.claude-sonnet-4-6-20241022-v2:0",
        context=RoutingContext(
            bedrock_region=REGION,
            timeout_seconds=30.0,
            max_retries=2,
            streaming=True,
        ),
        path=StrategistPath.DETERMINISTIC,
        blocked=blocked,
    )


# ---------------------------------------------------------------------------
# Mocked pipeline dependencies
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_presidio() -> AsyncMock:
    client = AsyncMock(spec=PresidioClient)
    client.anonymize = AsyncMock(return_value=make_redaction_result())
    return client


@pytest.fixture
def mock_bouncer() -> MagicMock:
    b = MagicMock()
    b.bounce = AsyncMock(return_value=make_bounce_result())
    return b


@pytest.fixture
def mock_classifier() -> MagicMock:
    c = MagicMock()
    c.classify = AsyncMock(return_value=make_intent_result())
    return c


@pytest.fixture
def mock_strategist() -> MagicMock:
    s = MagicMock()
    s.route = AsyncMock(return_value=make_routing_plan())
    return s


@pytest.fixture
def mock_audit() -> AsyncMock:
    return AsyncMock(spec=AuditLogger)


@pytest.fixture
def driver(
    redis_client,
    mock_presidio,
    mock_bouncer,
    mock_classifier,
    mock_strategist,
    mock_audit,
) -> PipelineDriver:
    return PipelineDriver(
        presidio=mock_presidio,
        redis=redis_client,
        bouncer=mock_bouncer,
        classifier=mock_classifier,
        strategist=mock_strategist,
        audit=mock_audit,
    )
