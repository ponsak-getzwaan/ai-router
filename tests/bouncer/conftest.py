"""Shared fixtures and helpers for all Bouncer tests."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

import fakeredis.aioredis  # type: ignore[import-untyped]
import pytest

from bouncer.config import BouncerConfig
from bouncer.llm_classifier import MetricPublisher
from shared.models import PipelineEnvelope


class NoOpMetrics:
    """MetricPublisher that discards all metrics. Used in unit tests."""

    async def put_count(self, metric_name: str) -> None:
        pass


assert isinstance(NoOpMetrics(), MetricPublisher), (
    "NoOpMetrics must satisfy MetricPublisher protocol"
)


@pytest.fixture
def config() -> BouncerConfig:
    return BouncerConfig(
        total_budget_ms=200.0,
        haiku_model_id="apac.test.fake-haiku:0",
        haiku_max_tokens=50,
        confidence_threshold=0.7,
        max_message_length=100,
        rate_limit_per_minute=5,
        redis_url="redis://localhost:6379",
        bedrock_region="ap-southeast-1",
        cloudwatch_namespace="AIRouter/Test",
    )


@pytest.fixture
async def redis() -> fakeredis.aioredis.FakeRedis:  # type: ignore[misc]
    r: fakeredis.aioredis.FakeRedis = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


def make_envelope(
    message: str = "Hello, can you help me?",
    user_sub: str = "user-abc-123",
    source_ip: str = "1.2.3.4",
) -> PipelineEnvelope:
    """Build a valid PipelineEnvelope for testing."""
    raw_hash = hashlib.sha256(message.encode()).hexdigest()
    return PipelineEnvelope(
        correlation_id=uuid4(),
        user_sub=user_sub,
        session_id="session-abc-123",
        redacted_message=message,
        raw_message_hash=raw_hash,
        entity_types_redacted=(),
        entity_count=0,
        was_redacted=False,
        timestamp=datetime.now(UTC),
        bedrock_region="ap-southeast-1",
        source_ip=source_ip,
    )
