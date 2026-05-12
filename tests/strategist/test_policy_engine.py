"""Unit tests for the policy engine.

Tests data-residency enforcement and compliance blocking, independently
of the vendor selector. All inputs are constructed directly from Pydantic models.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

import pytest

from shared.models import (
    ClassifiedIntent,
    ClassifierPath,
    IntentDomain,
    PipelineEnvelope,
    RoutingContext,
    RoutingPlan,
    StrategistPath,
)
from strategist.policy_engine import apply_policies

# ---------------------------------------------------------------------------
# Vendor IDs (same as in policy_engine.py)
# ---------------------------------------------------------------------------

_HAIKU = "apac.anthropic.claude-haiku-4-5-20241022-v1:0"
_SONNET = "apac.anthropic.claude-sonnet-4-6-20241022-v2:0"
_UNAPPROVED = "openai/gpt-4"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_envelope() -> PipelineEnvelope:
    msg = "Hello, can you help me?"
    return PipelineEnvelope(
        correlation_id=uuid.uuid4(),
        user_sub="test-user-sub",
        session_id="test-session",
        redacted_message=msg,
        raw_message_hash=hashlib.sha256(msg.encode()).hexdigest(),
        entity_types_redacted=(),
        entity_count=0,
        was_redacted=False,
        timestamp=datetime.now(UTC),
        bedrock_region="ap-southeast-1",
        source_ip="127.0.0.1",
    )


def _make_intent(intent: str = "general_qa") -> ClassifiedIntent:
    return ClassifiedIntent(
        intent=intent,
        domain=IntentDomain.GENERAL_QA,
        confidence=0.9,
        resolved_message="Hello, can you help me?",
        path=ClassifierPath.FAST,
        escalate=False,
    )


def _make_plan(vendor: str = _SONNET) -> RoutingPlan:
    return RoutingPlan(
        primary_vendor=vendor,
        fallback_chain=(_HAIKU,),
        context=RoutingContext(
            bedrock_region="ap-southeast-1",
            timeout_seconds=8.0,
            max_retries=2,
        ),
        path=StrategistPath.DETERMINISTIC,
    )


# ---------------------------------------------------------------------------
# Tests — data residency
# ---------------------------------------------------------------------------


class TestDataResidency:
    def test_approved_sonnet_vendor_no_modification(self):
        plan = apply_policies(_make_plan(_SONNET), _make_envelope(), _make_intent())
        assert plan.policy_modified is False
        assert plan.blocked is False
        assert plan.applied_policies == ()

    def test_approved_haiku_vendor_no_modification(self):
        plan = apply_policies(_make_plan(_HAIKU), _make_envelope(), _make_intent())
        assert plan.policy_modified is False
        assert plan.blocked is False
        assert "sg_residency" not in plan.applied_policies

    def test_unapproved_vendor_rerouted(self):
        plan = apply_policies(_make_plan(_UNAPPROVED), _make_envelope(), _make_intent())
        assert plan.primary_vendor != _UNAPPROVED
        assert plan.primary_vendor == _SONNET

    def test_unapproved_vendor_adds_sg_residency_policy(self):
        plan = apply_policies(_make_plan(_UNAPPROVED), _make_envelope(), _make_intent())
        assert "sg_residency" in plan.applied_policies

    def test_unapproved_vendor_policy_modified_true(self):
        plan = apply_policies(_make_plan(_UNAPPROVED), _make_envelope(), _make_intent())
        assert plan.policy_modified is True

    def test_unapproved_vendor_not_hard_blocked(self):
        # Residency rerouting is not a block — request still proceeds
        plan = apply_policies(_make_plan(_UNAPPROVED), _make_envelope(), _make_intent())
        assert plan.blocked is False


# ---------------------------------------------------------------------------
# Tests — compliance blocks
# ---------------------------------------------------------------------------


class TestComplianceBlocks:
    def test_blocked_intent_sets_blocked_true(self):
        intent = _make_intent("mas_regulated_advice")
        plan = apply_policies(_make_plan(_SONNET), _make_envelope(), intent)
        assert plan.blocked is True

    def test_blocked_intent_adds_mas_block_policy(self):
        intent = _make_intent("mas_regulated_advice")
        plan = apply_policies(_make_plan(_SONNET), _make_envelope(), intent)
        assert "mas_block" in plan.applied_policies

    def test_blocked_intent_policy_modified_true(self):
        intent = _make_intent("financial_advice")
        plan = apply_policies(_make_plan(_SONNET), _make_envelope(), intent)
        assert plan.policy_modified is True

    def test_legal_advice_is_blocked(self):
        intent = _make_intent("legal_advice")
        plan = apply_policies(_make_plan(_SONNET), _make_envelope(), intent)
        assert plan.blocked is True

    def test_financial_advice_is_blocked(self):
        intent = _make_intent("financial_advice")
        plan = apply_policies(_make_plan(_SONNET), _make_envelope(), intent)
        assert plan.blocked is True

    def test_clean_intent_not_blocked(self):
        plan = apply_policies(_make_plan(_SONNET), _make_envelope(), _make_intent("general_qa"))
        assert plan.blocked is False


# ---------------------------------------------------------------------------
# Tests — combined policies
# ---------------------------------------------------------------------------


class TestCombinedPolicies:
    def test_clean_request_empty_applied_policies(self):
        plan = apply_policies(_make_plan(_SONNET), _make_envelope(), _make_intent("general_qa"))
        assert plan.applied_policies == ()

    def test_both_residency_and_compliance_applied(self):
        intent = _make_intent("mas_regulated_advice")
        plan = apply_policies(_make_plan(_UNAPPROVED), _make_envelope(), intent)
        assert "sg_residency" in plan.applied_policies
        assert "mas_block" in plan.applied_policies
        assert plan.blocked is True
        assert plan.policy_modified is True

    def test_rerouted_vendor_preserved_in_plan(self):
        # After rerouting, the plan should carry the approved vendor, not the original
        plan = apply_policies(_make_plan(_UNAPPROVED), _make_envelope(), _make_intent())
        assert plan.primary_vendor == _SONNET

    def test_fallback_chain_preserved_after_policy(self):
        original = _make_plan(_SONNET)
        plan = apply_policies(original, _make_envelope(), _make_intent())
        assert plan.fallback_chain == original.fallback_chain

    def test_path_preserved_after_policy(self):
        original = _make_plan(_SONNET)
        plan = apply_policies(original, _make_envelope(), _make_intent())
        assert plan.path == original.path
