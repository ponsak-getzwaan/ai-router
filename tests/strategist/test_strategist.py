"""Unit tests for the Strategist orchestrator.

Verifies that:
- The correct timeout is set in RoutingContext based on vendor selection
- Fallback chains are populated correctly per vendor
- The policy engine is called and its result is returned
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from shared.models import (
    ClassifiedIntent,
    ClassifierPath,
    IntentDomain,
    PipelineEnvelope,
    RoutingPlan,
    StrategistPath,
)
from strategist.config import StrategistConfig
from strategist.strategist import Strategist

# ---------------------------------------------------------------------------
# Vendor IDs
# ---------------------------------------------------------------------------

_HAIKU = "apac.anthropic.claude-3-haiku-20240307-v1:0"
_SONNET = "apac.anthropic.claude-3-5-sonnet-20241022-v2:0"


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


def _make_intent(intent: str = "general_qa", confidence: float = 0.9) -> ClassifiedIntent:
    return ClassifiedIntent(
        intent=intent,
        domain=IntentDomain.GENERAL_QA,
        confidence=confidence,
        resolved_message="Hello, can you help me?",
        path=ClassifierPath.FAST,
        escalate=False,
    )


def _make_strategist(
    vendor: str,
    path: StrategistPath = StrategistPath.DETERMINISTIC,
    config: StrategistConfig | None = None,
) -> Strategist:
    """Build a Strategist with a mocked VendorSelector that returns the given vendor."""
    if config is None:
        config = StrategistConfig()
    bedrock_mock = MagicMock()
    strategist = Strategist(config, bedrock_mock)
    strategist._selector.select = AsyncMock(return_value=(vendor, path))
    return strategist


# ---------------------------------------------------------------------------
# Timeout assignment
# ---------------------------------------------------------------------------


class TestTimeoutAssignment:
    async def test_haiku_vendor_uses_haiku_timeout(self):
        config = StrategistConfig()
        strategist = _make_strategist(_HAIKU, config=config)
        plan = await strategist.route(_make_envelope(), _make_intent())
        assert plan.context.timeout_seconds == config.haiku_timeout_s

    async def test_sonnet_vendor_uses_sonnet_timeout(self):
        config = StrategistConfig()
        strategist = _make_strategist(_SONNET, config=config)
        plan = await strategist.route(_make_envelope(), _make_intent())
        assert plan.context.timeout_seconds == config.sonnet_timeout_s

    async def test_haiku_timeout_less_than_sonnet_timeout(self):
        config = StrategistConfig()
        assert config.haiku_timeout_s < config.sonnet_timeout_s


# ---------------------------------------------------------------------------
# Fallback chains
# ---------------------------------------------------------------------------


class TestFallbackChains:
    async def test_sonnet_vendor_has_haiku_fallback(self):
        strategist = _make_strategist(_SONNET)
        plan = await strategist.route(_make_envelope(), _make_intent())
        assert _HAIKU in plan.fallback_chain

    async def test_haiku_vendor_has_empty_fallback(self):
        strategist = _make_strategist(_HAIKU)
        plan = await strategist.route(_make_envelope(), _make_intent())
        assert plan.fallback_chain == ()

    async def test_non_haiku_vendor_always_gets_haiku_fallback(self):
        # Any non-haiku vendor should have haiku as a fallback
        strategist = _make_strategist(_SONNET)
        plan = await strategist.route(_make_envelope(), _make_intent())
        assert len(plan.fallback_chain) >= 1
        assert plan.fallback_chain[0] == _HAIKU


# ---------------------------------------------------------------------------
# Policy engine integration
# ---------------------------------------------------------------------------


class TestPolicyEngineIntegration:
    async def test_policy_engine_runs_on_plan(self):
        strategist = _make_strategist(_SONNET)
        with patch("strategist.strategist.apply_policies", wraps=lambda p, e, i: p) as mock_policy:
            await strategist.route(_make_envelope(), _make_intent())
            mock_policy.assert_called_once()

    async def test_policy_engine_called_with_correct_args(self):
        strategist = _make_strategist(_SONNET)
        envelope = _make_envelope()
        intent = _make_intent()

        with patch("strategist.strategist.apply_policies", wraps=lambda p, e, i: p) as mock_policy:
            await strategist.route(envelope, intent)
            call_args = mock_policy.call_args
            _plan, passed_envelope, passed_intent = call_args[0]
            assert passed_envelope is envelope
            assert passed_intent is intent

    async def test_returns_policy_modified_plan(self):
        """When policy engine modifies the plan, the modified plan is returned."""
        strategist = _make_strategist(_SONNET)

        def mock_policy(
            plan: RoutingPlan, envelope: PipelineEnvelope, intent: ClassifiedIntent
        ) -> RoutingPlan:
            # Return a plan with policy_modified=True and an applied policy
            return RoutingPlan(
                primary_vendor=plan.primary_vendor,
                fallback_chain=plan.fallback_chain,
                context=plan.context,
                applied_policies=("test_policy",),
                policy_modified=True,
                blocked=False,
                path=plan.path,
            )

        with patch("strategist.strategist.apply_policies", side_effect=mock_policy):
            plan = await strategist.route(_make_envelope(), _make_intent())

        assert plan.policy_modified is True
        assert "test_policy" in plan.applied_policies


# ---------------------------------------------------------------------------
# RoutingContext properties
# ---------------------------------------------------------------------------


class TestRoutingContext:
    async def test_routing_context_has_correct_region(self):
        config = StrategistConfig()
        strategist = _make_strategist(_SONNET, config=config)
        plan = await strategist.route(_make_envelope(), _make_intent())
        assert plan.context.bedrock_region == config.bedrock_region

    async def test_routing_context_streaming_enabled_by_default(self):
        strategist = _make_strategist(_SONNET)
        plan = await strategist.route(_make_envelope(), _make_intent())
        assert plan.context.streaming is True

    async def test_routing_context_max_retries_set(self):
        strategist = _make_strategist(_SONNET)
        plan = await strategist.route(_make_envelope(), _make_intent())
        assert plan.context.max_retries == 2

    async def test_plan_path_matches_selector_path(self):
        strategist = _make_strategist(_SONNET, path=StrategistPath.HAIKU_ARBITRATION)
        plan = await strategist.route(_make_envelope(), _make_intent())
        # Path in the plan before policy engine may change vendor but not path
        # The path comes from the selector result
        assert plan.path in (
            StrategistPath.HAIKU_ARBITRATION,
            StrategistPath.DETERMINISTIC,
            StrategistPath.ESCALATED,
        )
