"""Pydantic model validation tests for admin.models.

Verifies that the model definitions themselves enforce the PII constraints
and field invariants — independent of any HTTP endpoint behaviour.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from admin.models import (
    AuditRecord,
    EscalationMessage,
    RoutingRuleUpdate,
)
from admin.models import (
    TestConsoleRequest as ConsoleRequest,
)


class TestAuditRecordSchema:
    def test_no_message_field_in_model(self) -> None:
        """AuditRecord must not have a 'message' field in its schema."""
        fields = AuditRecord.model_fields
        forbidden = {"message", "raw_message", "redacted_message", "content", "prompt"}
        present = forbidden & set(fields)
        assert not present, f"Forbidden fields found in AuditRecord: {present}"

    def test_entity_types_is_list_of_strings(self) -> None:
        record = AuditRecord(
            correlation_id="cid",
            timestamp="2026-01-01T00:00:00+00:00",
            user_sub="sub",
            session_id="sess",
            entity_types_redacted=["SG_NRIC", "CREDIT_CARD"],
            entity_count=2,
            was_redacted=True,
            bouncer_allowed=True,
            bouncer_escalated=False,
            intent="general_qa",
            intent_confidence="0.92",
            vendor="apac.anthropic.claude-3-5-sonnet-20241022-v2:0",
            routing_path="deterministic",
            policy_blocked=False,
            total_latency_ms="342.5",
            error_type=None,
        )
        assert record.entity_types_redacted == ["SG_NRIC", "CREDIT_CARD"]

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AuditRecord(  # type: ignore[call-arg]
                correlation_id="cid",
                timestamp="2026-01-01T00:00:00+00:00",
                user_sub="sub",
                session_id="sess",
                entity_types_redacted=[],
                entity_count=0,
                was_redacted=False,
                bouncer_allowed=None,
                bouncer_escalated=None,
                intent=None,
                intent_confidence=None,
                vendor=None,
                routing_path=None,
                policy_blocked=None,
                total_latency_ms=None,
                error_type=None,
                raw_message="PII",  # must be rejected
            )

    def test_optional_fields_may_be_none(self) -> None:
        record = AuditRecord(
            correlation_id="cid",
            timestamp="2026-01-01T00:00:00+00:00",
            user_sub="sub",
            session_id="sess",
            entity_types_redacted=[],
            entity_count=0,
            was_redacted=False,
            bouncer_allowed=None,
            bouncer_escalated=None,
            intent=None,
            intent_confidence=None,
            vendor=None,
            routing_path=None,
            policy_blocked=None,
            total_latency_ms=None,
            error_type=None,
        )
        assert record.intent is None
        assert record.vendor is None


class TestEscalationMessageSchema:
    def test_no_raw_message_field(self) -> None:
        fields = EscalationMessage.model_fields
        assert "raw_message" not in fields
        assert "original" not in fields

    def test_redacted_preview_field_exists(self) -> None:
        assert "redacted_preview" in EscalationMessage.model_fields

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EscalationMessage(  # type: ignore[call-arg]
                receipt_handle="rh",
                message_id="mid",
                correlation_id="cid",
                user_sub="sub",
                session_id="sess",
                redacted_preview="VAULT_ABC",
                entity_types=[],
                bouncer_reason=None,
                sent_at=None,
                approximate_receive_count=0,
                raw_message="actual PII",  # must be rejected
            )

    def test_valid_message_accepted(self) -> None:
        msg = EscalationMessage(
            receipt_handle="rh",
            message_id="mid",
            correlation_id="cid",
            user_sub="sub",
            session_id="sess",
            redacted_preview="What is VAULT_3A4B?",
            entity_types=["SG_NRIC"],
            bouncer_reason="low_confidence",
            sent_at=datetime.now(UTC),
            approximate_receive_count=1,
        )
        assert msg.redacted_preview == "What is VAULT_3A4B?"


class TestRoutingRuleUpdateSchema:
    def test_empty_vendor_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RoutingRuleUpdate(vendor="")

    def test_vendor_too_long_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RoutingRuleUpdate(vendor="x" * 201)

    def test_valid_vendor_accepted(self) -> None:
        rule = RoutingRuleUpdate(vendor="apac.anthropic.claude-3-5-sonnet-20241022-v2:0")
        assert rule.vendor == "apac.anthropic.claude-3-5-sonnet-20241022-v2:0"

    def test_fallback_and_description_optional(self) -> None:
        rule = RoutingRuleUpdate(vendor="apac.anthropic.claude-3-haiku-20240307-v1:0")
        assert rule.fallback is None
        assert rule.description is None

    def test_description_too_long_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RoutingRuleUpdate(
                vendor="apac.anthropic.claude-3-haiku-20240307-v1:0",
                description="x" * 501,
            )

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RoutingRuleUpdate(  # type: ignore[call-arg]
                vendor="apac.anthropic.claude-3-haiku-20240307-v1:0",
                unknown="bad",
            )


class TestConsoleRequestSchema:
    def test_empty_message_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ConsoleRequest(message="")

    def test_message_over_4096_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ConsoleRequest(message="x" * 4097)

    def test_message_at_4096_accepted(self) -> None:
        req = ConsoleRequest(message="x" * 4096)
        assert len(req.message) == 4096

    def test_user_sub_has_default(self) -> None:
        req = ConsoleRequest(message="hello")
        assert req.user_sub == "admin-test-user"

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ConsoleRequest(  # type: ignore[call-arg]
                message="hello",
                raw_input="bad",
            )
