"""Unit tests for the VendorSelector.

Three routing paths:
  >= 0.85 → DETERMINISTIC (DynamoDB lookup, then local map)
  0.5 – 0.85 → HAIKU_ARBITRATION (Bedrock Haiku call)
  < 0.5 → ESCALATED (default vendor, no LLM)

All Bedrock and DynamoDB calls are mocked.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.errors import BedrockError
from shared.models import ClassifiedIntent, ClassifierPath, IntentDomain, StrategistPath
from strategist.config import StrategistConfig
from strategist.vendor_selector import VendorSelector, _INTENT_TO_VENDOR

# ---------------------------------------------------------------------------
# Vendor IDs
# ---------------------------------------------------------------------------

_HAIKU = "apac.anthropic.claude-haiku-4-5-20241022-v1:0"
_SONNET = "apac.anthropic.claude-sonnet-4-6-20241022-v2:0"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_intent(
    intent: str = "general_qa",
    confidence: float = 0.9,
    domain: IntentDomain = IntentDomain.GENERAL_QA,
) -> ClassifiedIntent:
    return ClassifiedIntent(
        intent=intent,
        domain=domain,
        confidence=confidence,
        resolved_message="test message",
        path=ClassifierPath.FAST,
        escalate=False,
    )


def _bedrock_vendor_response(vendor: str) -> dict[str, Any]:
    payload = {"vendor": vendor, "reasoning": "test"}
    return {"content": [{"type": "text", "text": json.dumps(payload)}]}


def _make_dynamo_session(item: dict[str, Any] | None = None) -> MagicMock:
    """Build a mock aioboto3 session whose DynamoDB table.get_item returns item."""
    table_mock = MagicMock()
    table_mock.get_item = AsyncMock(
        return_value={"Item": item} if item is not None else {"Item": None}
    )

    # dynamo.Table() must be awaitable (it's called with `await dynamo.Table(...)`)
    async def table_factory(name: str) -> MagicMock:
        return table_mock

    dynamo_mock = MagicMock()
    dynamo_mock.Table = table_factory

    # The resource context manager: `async with session.resource(...) as dynamo:`
    resource_cm = MagicMock()
    resource_cm.__aenter__ = AsyncMock(return_value=dynamo_mock)
    resource_cm.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.resource = MagicMock(return_value=resource_cm)
    return session


def _make_selector(
    bedrock_mock: MagicMock,
    dynamo_session: MagicMock | None = None,
    config: StrategistConfig | None = None,
) -> VendorSelector:
    if config is None:
        config = StrategistConfig()
    if dynamo_session is None:
        dynamo_session = _make_dynamo_session()
    return VendorSelector(config, bedrock_mock, dynamo_session)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config() -> StrategistConfig:
    return StrategistConfig()


@pytest.fixture
def bedrock_mock() -> MagicMock:
    mock = MagicMock()
    mock.invoke_model = AsyncMock()
    return mock


# ---------------------------------------------------------------------------
# Confidence thresholds → path selection
# ---------------------------------------------------------------------------


class TestPathSelection:
    async def test_high_confidence_uses_deterministic_path(self, config, bedrock_mock):
        session = _make_dynamo_session({"vendor": _SONNET})
        selector = _make_selector(bedrock_mock, session, config)
        _vendor, path = await selector.select(_make_intent(confidence=0.85))
        assert path == StrategistPath.DETERMINISTIC

    async def test_confidence_just_at_deterministic_threshold(self, config, bedrock_mock):
        session = _make_dynamo_session({"vendor": _SONNET})
        selector = _make_selector(bedrock_mock, session, config)
        _vendor, path = await selector.select(_make_intent(confidence=config.deterministic_threshold))
        assert path == StrategistPath.DETERMINISTIC

    async def test_medium_confidence_uses_haiku_arbitration(self, config, bedrock_mock):
        bedrock_mock.invoke_model.return_value = _bedrock_vendor_response(_SONNET)
        selector = _make_selector(bedrock_mock, config=config)
        _vendor, path = await selector.select(_make_intent(confidence=0.7))
        assert path == StrategistPath.HAIKU_ARBITRATION

    async def test_confidence_just_below_deterministic_uses_haiku(self, config, bedrock_mock):
        bedrock_mock.invoke_model.return_value = _bedrock_vendor_response(_HAIKU)
        selector = _make_selector(bedrock_mock, config=config)
        _vendor, path = await selector.select(
            _make_intent(confidence=config.deterministic_threshold - 0.01)
        )
        assert path == StrategistPath.HAIKU_ARBITRATION

    async def test_low_confidence_escalates(self, config, bedrock_mock):
        selector = _make_selector(bedrock_mock, config=config)
        _vendor, path = await selector.select(_make_intent(confidence=0.3))
        assert path == StrategistPath.ESCALATED

    async def test_confidence_just_below_escalate_threshold_uses_haiku(self, config, bedrock_mock):
        bedrock_mock.invoke_model.return_value = _bedrock_vendor_response(_HAIKU)
        selector = _make_selector(bedrock_mock, config=config)
        _vendor, path = await selector.select(
            _make_intent(confidence=config.escalate_threshold)
        )
        # escalate_threshold=0.5; confidence==0.5 is NOT < threshold → haiku path
        assert path == StrategistPath.HAIKU_ARBITRATION

    async def test_confidence_zero_escalates(self, config, bedrock_mock):
        selector = _make_selector(bedrock_mock, config=config)
        _vendor, path = await selector.select(_make_intent(confidence=0.0))
        assert path == StrategistPath.ESCALATED


# ---------------------------------------------------------------------------
# Deterministic path — DynamoDB hit/miss and local map
# ---------------------------------------------------------------------------


class TestDeterministicPath:
    async def test_dynamo_hit_returns_dynamo_vendor(self, config, bedrock_mock):
        session = _make_dynamo_session({"vendor": _HAIKU, "intent": "code_assistance"})
        selector = _make_selector(bedrock_mock, session, config)
        vendor, _path = await selector.select(_make_intent("code_assistance", confidence=0.9))
        assert vendor == _HAIKU

    async def test_dynamo_miss_falls_back_to_local_map(self, config, bedrock_mock):
        # item=None → DynamoDB miss → fall back to _INTENT_TO_VENDOR
        session = _make_dynamo_session(item=None)
        selector = _make_selector(bedrock_mock, session, config)
        vendor, _path = await selector.select(_make_intent("code_assistance", confidence=0.9))
        expected = _INTENT_TO_VENDOR.get("code_assistance", config.default_vendor)
        assert vendor == expected

    async def test_code_assistance_maps_to_sonnet_in_local_map(self, config, bedrock_mock):
        session = _make_dynamo_session(item=None)
        selector = _make_selector(bedrock_mock, session, config)
        vendor, _path = await selector.select(_make_intent("code_assistance", confidence=0.9))
        assert vendor == _SONNET

    async def test_simple_transactional_maps_to_haiku_in_local_map(self, config, bedrock_mock):
        session = _make_dynamo_session(item=None)
        selector = _make_selector(bedrock_mock, session, config)
        vendor, _path = await selector.select(
            _make_intent("simple_transactional", confidence=0.9)
        )
        assert vendor == _HAIKU

    async def test_dynamo_error_falls_back_to_local_map(self, config, bedrock_mock):
        session = MagicMock()
        # Make resource() return a context manager that raises on __aenter__
        resource_cm = MagicMock()
        resource_cm.__aenter__ = AsyncMock(side_effect=Exception("DynamoDB connection failed"))
        resource_cm.__aexit__ = AsyncMock(return_value=False)
        session.resource = MagicMock(return_value=resource_cm)

        selector = _make_selector(bedrock_mock, session, config)
        vendor, path = await selector.select(_make_intent("code_assistance", confidence=0.9))
        assert path == StrategistPath.DETERMINISTIC
        assert vendor == _INTENT_TO_VENDOR.get("code_assistance", config.default_vendor)

    async def test_unknown_intent_falls_back_to_default_vendor(self, config, bedrock_mock):
        session = _make_dynamo_session(item=None)
        selector = _make_selector(bedrock_mock, session, config)
        vendor, _path = await selector.select(
            _make_intent("totally_unknown_intent", confidence=0.9)
        )
        assert vendor == config.default_vendor

    async def test_deterministic_does_not_call_bedrock(self, config, bedrock_mock):
        session = _make_dynamo_session({"vendor": _SONNET})
        selector = _make_selector(bedrock_mock, session, config)
        await selector.select(_make_intent(confidence=0.9))
        bedrock_mock.invoke_model.assert_not_called()


# ---------------------------------------------------------------------------
# Haiku arbitration path
# ---------------------------------------------------------------------------


class TestHaikuArbitration:
    async def test_haiku_arbitration_uses_bedrock_vendor(self, config, bedrock_mock):
        bedrock_mock.invoke_model.return_value = _bedrock_vendor_response(_HAIKU)
        selector = _make_selector(bedrock_mock, config=config)
        vendor, _path = await selector.select(_make_intent(confidence=0.7))
        assert vendor == _HAIKU

    async def test_haiku_arbitration_calls_bedrock(self, config, bedrock_mock):
        bedrock_mock.invoke_model.return_value = _bedrock_vendor_response(_SONNET)
        selector = _make_selector(bedrock_mock, config=config)
        await selector.select(_make_intent(confidence=0.7))
        bedrock_mock.invoke_model.assert_called_once()

    async def test_haiku_arbitration_falls_back_on_bedrock_error(self, config, bedrock_mock):
        bedrock_mock.invoke_model.side_effect = BedrockError("ServiceUnavailable")
        selector = _make_selector(bedrock_mock, config=config)
        vendor, path = await selector.select(
            _make_intent("code_assistance", confidence=0.7)
        )
        assert path == StrategistPath.HAIKU_ARBITRATION
        expected = _INTENT_TO_VENDOR.get("code_assistance", config.default_vendor)
        assert vendor == expected

    async def test_haiku_arbitration_falls_back_on_malformed_json(self, config, bedrock_mock):
        bedrock_mock.invoke_model.return_value = {
            "content": [{"type": "text", "text": "not valid json"}]
        }
        selector = _make_selector(bedrock_mock, config=config)
        vendor, _path = await selector.select(
            _make_intent("simple_transactional", confidence=0.7)
        )
        expected = _INTENT_TO_VENDOR.get("simple_transactional", config.default_vendor)
        assert vendor == expected

    async def test_haiku_arbitration_falls_back_on_missing_vendor_key(self, config, bedrock_mock):
        # Response JSON doesn't have "vendor" key → falls back
        bedrock_mock.invoke_model.return_value = {
            "content": [{"type": "text", "text": json.dumps({"reasoning": "hmm"})}]
        }
        selector = _make_selector(bedrock_mock, config=config)
        vendor, _path = await selector.select(
            _make_intent("general_qa", confidence=0.7)
        )
        # Should return default_vendor since "vendor" key missing
        assert vendor == config.default_vendor


# ---------------------------------------------------------------------------
# Escalated path
# ---------------------------------------------------------------------------


class TestEscalatedPath:
    async def test_escalated_returns_default_vendor(self, config, bedrock_mock):
        selector = _make_selector(bedrock_mock, config=config)
        vendor, _path = await selector.select(_make_intent(confidence=0.1))
        assert vendor == config.default_vendor

    async def test_escalated_does_not_call_bedrock(self, config, bedrock_mock):
        selector = _make_selector(bedrock_mock, config=config)
        await selector.select(_make_intent(confidence=0.1))
        bedrock_mock.invoke_model.assert_not_called()
