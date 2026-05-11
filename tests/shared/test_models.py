"""Contract tests for shared.models.

These verify the invariants that the rest of the pipeline relies on:
  - Frozen models can't be mutated after construction.
  - Models reject extra fields.
  - Each model round-trips through JSON cleanly.
  - The custom validators (timezone-aware timestamp, hash format,
    entity_count >= unique types, reason field doesn't contain PII)
    actually fire.

If any of these tests fail, pipeline code that depends on the contracts will
break in subtle ways. Don't relax these tests; fix the production code instead.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from shared.models import (
    BounceResult,
    BouncerLayer,
    ClassifiedIntent,
    ClassifierPath,
    Entity,
    EntityType,
    IntentDomain,
    PipelineEnvelope,
    RedactionResult,
    RoutingContext,
    RoutingPlan,
    StrategistPath,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def correlation_id():
    return uuid4()


@pytest.fixture
def example_envelope(correlation_id):
    return PipelineEnvelope(
        correlation_id=correlation_id,
        user_sub="cognito-uuid-abc",
        session_id="session-123",
        redacted_message="Hi, I'm <SG_NRIC_1>.",
        raw_message_hash="a" * 64,
        entity_types_redacted=(EntityType.SG_NRIC,),
        entity_count=1,
        was_redacted=True,
        source_ip="203.0.113.42",
    )


# =============================================================================
# Frozen-ness
# =============================================================================


class TestImmutability:
    """Every handoff model must be immutable post-construction."""

    def test_bounce_result_is_frozen(self):
        result = BounceResult(
            allowed=True,
            reason="rule_gate_pass",
            layer=BouncerLayer.RULE_GATE,
            confidence=0.95,
        )
        with pytest.raises(ValidationError):
            result.allowed = False  # type: ignore[misc]

    def test_routing_plan_is_frozen(self):
        plan = RoutingPlan(
            primary_vendor="claude-sonnet-bedrock",
            context=RoutingContext(timeout_seconds=8.0, max_retries=2),
            path=StrategistPath.DETERMINISTIC,
        )
        with pytest.raises(ValidationError):
            plan.primary_vendor = "something_else"  # type: ignore[misc]

    def test_pipeline_envelope_is_frozen(self, example_envelope):
        with pytest.raises(ValidationError):
            example_envelope.user_sub = "different-sub"  # type: ignore[misc]


# =============================================================================
# Extra field rejection
# =============================================================================


class TestExtraFieldsForbidden:
    """Silent field drops are bugs. Reject extras loudly."""

    def test_bounce_result_rejects_extra(self):
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            BounceResult(
                allowed=True,
                reason="ok",
                layer=BouncerLayer.RULE_GATE,
                confidence=0.9,
                extra_field="leaked_user_input",  # type: ignore[call-arg]
            )

    def test_classified_intent_rejects_extra(self):
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            ClassifiedIntent(
                intent="general_question",
                domain=IntentDomain.GENERAL_QA,
                confidence=0.7,
                resolved_message="hello",
                path=ClassifierPath.FAST,
                debug_message="this is the raw user input",  # type: ignore[call-arg]
            )


# =============================================================================
# JSON round-trip
# =============================================================================


class TestJsonRoundTrip:
    """Every handoff type must serialise to JSON and back without loss."""

    def test_bounce_result_round_trips(self):
        original = BounceResult(
            allowed=False,
            reason="prompt_injection_detected",
            layer=BouncerLayer.RULE_GATE,
            confidence=0.99,
            escalate=True,
        )
        json_str = original.model_dump_json()
        restored = BounceResult.model_validate_json(json_str)
        assert restored == original

    def test_pipeline_envelope_round_trips(self, example_envelope):
        json_str = example_envelope.model_dump_json()
        restored = PipelineEnvelope.model_validate_json(json_str)
        assert restored == example_envelope

    def test_routing_plan_round_trips(self):
        original = RoutingPlan(
            primary_vendor="claude-sonnet-bedrock",
            fallback_chain=("claude-haiku-bedrock", "escalation"),
            context=RoutingContext(timeout_seconds=8.0, max_retries=2),
            applied_policies=("sg_residency",),
            path=StrategistPath.DETERMINISTIC,
        )
        json_str = original.model_dump_json()
        restored = RoutingPlan.model_validate_json(json_str)
        assert restored == original


# =============================================================================
# Validators
# =============================================================================


class TestValidators:
    """Custom validators actually fire."""

    def test_timestamp_must_be_timezone_aware(self):
        with pytest.raises(ValidationError, match="timezone-aware"):
            PipelineEnvelope(
                correlation_id=uuid4(),
                user_sub="abc",
                session_id="s",
                redacted_message="hi",
                raw_message_hash="a" * 64,
                entity_count=0,
                was_redacted=False,
                source_ip="1.2.3.4",
                timestamp=datetime(2026, 1, 1),  # naive
            )

    def test_hash_must_be_64_hex_chars(self):
        with pytest.raises(ValidationError):
            PipelineEnvelope(
                correlation_id=uuid4(),
                user_sub="abc",
                session_id="s",
                redacted_message="hi",
                raw_message_hash="not_a_hash",
                entity_count=0,
                was_redacted=False,
                source_ip="1.2.3.4",
            )

    def test_hash_rejects_uppercase(self):
        with pytest.raises(ValidationError):
            PipelineEnvelope(
                correlation_id=uuid4(),
                user_sub="abc",
                session_id="s",
                redacted_message="hi",
                raw_message_hash="A" * 64,  # uppercase rejected
                entity_count=0,
                was_redacted=False,
                source_ip="1.2.3.4",
            )

    def test_entity_count_at_least_unique_types(self):
        with pytest.raises(ValidationError, match="entity_count"):
            RedactionResult(
                redacted_message="hi",
                entity_types_found=(EntityType.SG_NRIC, EntityType.CREDIT_CARD),
                entity_count=1,  # but 2 unique types found
                was_redacted=True,
                correlation_id=uuid4(),
            )

    def test_entity_count_can_exceed_unique_types(self):
        """Same type appearing multiple times is fine."""
        result = RedactionResult(
            redacted_message="hi",
            entity_types_found=(EntityType.SG_NRIC,),
            entity_count=3,  # NRIC appeared 3 times
            was_redacted=True,
            correlation_id=uuid4(),
        )
        assert result.entity_count == 3

    def test_entity_end_must_be_after_start(self):
        with pytest.raises(ValidationError, match="end must be greater"):
            Entity(type=EntityType.PERSON, value="Alice", start=10, end=5)

    def test_bedrock_region_pattern(self):
        with pytest.raises(ValidationError):
            RoutingContext(
                bedrock_region="us-east-1-typo-extra",
                timeout_seconds=8.0,
                max_retries=2,
            )

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            BounceResult(
                allowed=True,
                reason="ok",
                layer=BouncerLayer.RULE_GATE,
                confidence=1.5,  # out of bounds
            )
        with pytest.raises(ValidationError):
            BounceResult(
                allowed=True,
                reason="ok",
                layer=BouncerLayer.RULE_GATE,
                confidence=-0.1,  # out of bounds
            )


# =============================================================================
# Reason field — anti-PII guard
# =============================================================================


class TestReasonAntiPii:
    """The reason field is a code, not a message body. Catch obvious leaks."""

    def test_reason_rejects_newlines(self):
        with pytest.raises(ValidationError, match="short code"):
            BounceResult(
                allowed=True,
                reason="ok\nuser said: hello",
                layer=BouncerLayer.RULE_GATE,
                confidence=0.9,
            )

    def test_reason_rejects_email_marker(self):
        with pytest.raises(ValidationError, match="short code"):
            BounceResult(
                allowed=False,
                reason="user@example.com violated policy",
                layer=BouncerLayer.LLM_CLASSIFIER,
                confidence=0.99,
            )

    def test_reason_accepts_short_code(self):
        result = BounceResult(
            allowed=False,
            reason="prompt_injection_detected",
            layer=BouncerLayer.RULE_GATE,
            confidence=0.99,
        )
        assert result.reason == "prompt_injection_detected"


# =============================================================================
# Bouncer fail-open semantics
# =============================================================================


class TestBouncerFailOpen:
    """The fail-open path is the one most likely to be coded incorrectly.

    Per CLAUDE.md §7 and the project spec: on timeout, the request is
    ALLOWED downstream with timed_out=True. Test that we can construct
    such a result without the type system fighting us.
    """

    def test_can_construct_fail_open_result(self):
        result = BounceResult(
            allowed=True,
            reason="bouncer_timeout",
            layer=BouncerLayer.TIMEOUT_FAIL_OPEN,
            confidence=0.0,
            timed_out=True,
            escalate=False,
        )
        assert result.allowed is True
        assert result.timed_out is True
        assert result.layer == BouncerLayer.TIMEOUT_FAIL_OPEN
