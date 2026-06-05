"""Unit tests for orchestrator.pipeline_driver.PipelineDriver.

All dependencies (Presidio, Redis/vault, Bouncer, Classifier, Strategist,
Audit, vendor adapter) are mocked. No real AWS / Presidio / LiteLLM calls.
asyncio_mode=auto means no @pytest.mark.asyncio needed.
"""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import fakeredis.aioredis  # type: ignore[import-untyped]

from orchestrator.pipeline_driver import PipelineDriver
from shared.errors import PresidioError
from shared.models import (
    BounceResult,
    BouncerLayer,
    ClassifiedIntent,
    ClassifierPath,
    EntityType,
    IntentDomain,
    PipelineEnvelope,
    RedactionResult,
    RoutingContext,
    RoutingPlan,
    StrategistPath,
)

# =============================================================================
# Constants
# =============================================================================

_USER_SUB = "user-sub-abc-123"
_SESSION_ID = "session-id-xyz"
_SOURCE_IP = "10.0.0.1"
_RAW_MESSAGE = "Hello, please help me with my NRIC S1234567A"
_REDACTED_MESSAGE = "Hello, please help me with my NRIC VAULT_TOKEN_AAAA"
_VENDOR_RESPONSE_WITH_TOKEN = "Sure, VAULT_TOKEN_AAAA is noted."
_VENDOR_RESPONSE_CLEAN = "Sure, that is noted."


# =============================================================================
# Helpers
# =============================================================================


def make_redaction_result(
    redacted: str = _REDACTED_MESSAGE,
    was_redacted: bool = True,
    entity_types: tuple[EntityType, ...] = (EntityType.SG_NRIC,),
    entity_count: int = 1,
) -> RedactionResult:
    return RedactionResult(
        redacted_message=redacted,
        entity_types_found=entity_types,
        entity_count=entity_count,
        was_redacted=was_redacted,
        correlation_id=uuid4(),
    )


def make_bounce(allowed: bool = True, escalate: bool = False) -> BounceResult:
    return BounceResult(
        allowed=allowed,
        reason="safe" if allowed else "banned_user",
        layer=BouncerLayer.LLM_CLASSIFIER,
        confidence=0.9,
        escalate=escalate,
    )


def make_intent(escalate: bool = False) -> ClassifiedIntent:
    return ClassifiedIntent(
        intent="general_qa",
        domain=IntentDomain.GENERAL_QA,
        confidence=0.88,
        resolved_message=_REDACTED_MESSAGE,
        path=ClassifierPath.FAST,
        escalate=escalate,
    )


def make_plan(blocked: bool = False) -> RoutingPlan:
    return RoutingPlan(
        primary_vendor="apac.anthropic.claude-3-5-sonnet-20241022-v2:0",
        fallback_chain=(),
        context=RoutingContext(timeout_seconds=10.0, max_retries=2, streaming=False),
        path=StrategistPath.DETERMINISTIC,
        blocked=blocked,
    )


async def make_driver(
    presidio_redaction: RedactionResult | None = None,
    presidio_raises: Exception | None = None,
    bounce_result: BounceResult | None = None,
    intent_result: ClassifiedIntent | None = None,
    plan_result: RoutingPlan | None = None,
    vendor_response: str = _VENDOR_RESPONSE_WITH_TOKEN,
) -> tuple[PipelineDriver, fakeredis.aioredis.FakeRedis]:
    """Build a PipelineDriver with all deps mocked, plus a real fakeredis."""
    redis: fakeredis.aioredis.FakeRedis = fakeredis.aioredis.FakeRedis()

    presidio = AsyncMock()
    if presidio_raises is not None:
        presidio.anonymize = AsyncMock(side_effect=presidio_raises)
    else:
        presidio.anonymize = AsyncMock(
            return_value=presidio_redaction or make_redaction_result()
        )

    bouncer = AsyncMock()
    bouncer.bounce = AsyncMock(return_value=bounce_result or make_bounce())

    classifier = AsyncMock()
    classifier.classify = AsyncMock(return_value=intent_result or make_intent())

    strategist = AsyncMock()
    strategist.route = AsyncMock(return_value=plan_result or make_plan())

    audit = AsyncMock()
    audit.write = AsyncMock()

    history = AsyncMock()
    history.get = AsyncMock(return_value=[])
    history.append = AsyncMock()

    driver = PipelineDriver(
        presidio=presidio,
        redis=redis,
        bouncer=bouncer,
        classifier=classifier,
        strategist=strategist,
        audit=audit,
        history=history,
        vault_ttl_seconds=300,
    )
    return driver, redis


# =============================================================================
# Happy path
# =============================================================================


async def test_happy_path_returns_restored_response() -> None:
    """Full pipeline run: token in vendor response is restored."""
    driver, _redis = await make_driver(vendor_response=_VENDOR_RESPONSE_WITH_TOKEN)

    # Pre-store a vault token so restore can replace it
    cid = uuid4()
    await driver._vault.store(str(cid), {"VAULT_TOKEN_AAAA": "S1234567A"})

    with patch(
        "orchestrator.pipeline_driver.vendor_adapter.invoke",
        new_callable=AsyncMock,
        return_value=_VENDOR_RESPONSE_WITH_TOKEN,
    ):
        result = await driver.run(
            raw_message=_RAW_MESSAGE,
            user_sub=_USER_SUB,
            session_id=_SESSION_ID,
            correlation_id=cid,
            source_ip=_SOURCE_IP,
        )

    # Vault had the token pre-loaded, so restoration should have worked
    assert "VAULT_TOKEN_AAAA" not in result or "S1234567A" in result


async def test_happy_path_clean_response_returned_as_is() -> None:
    """Vendor response without vault tokens is returned unchanged."""
    driver, _ = await make_driver(
        presidio_redaction=make_redaction_result(
            redacted="Clean input", was_redacted=False, entity_types=(), entity_count=0
        ),
        vendor_response=_VENDOR_RESPONSE_CLEAN,
    )

    with patch(
        "orchestrator.pipeline_driver.vendor_adapter.invoke",
        new_callable=AsyncMock,
        return_value=_VENDOR_RESPONSE_CLEAN,
    ):
        result = await driver.run(
            raw_message="Clean input",
            user_sub=_USER_SUB,
            session_id=_SESSION_ID,
            correlation_id=uuid4(),
            source_ip=_SOURCE_IP,
        )

    assert result == _VENDOR_RESPONSE_CLEAN


# =============================================================================
# Bouncer blocking
# =============================================================================


async def test_bouncer_block_returns_cannot_process_message() -> None:
    driver, _ = await make_driver(bounce_result=make_bounce(allowed=False))

    with patch("orchestrator.pipeline_driver.vendor_adapter.invoke", new_callable=AsyncMock):
        result = await driver.run(
            raw_message=_RAW_MESSAGE,
            user_sub=_USER_SUB,
            session_id=_SESSION_ID,
            correlation_id=uuid4(),
            source_ip=_SOURCE_IP,
        )

    assert "cannot be processed" in result.lower()


async def test_bouncer_block_skips_classifier() -> None:
    driver, _ = await make_driver(bounce_result=make_bounce(allowed=False))

    with patch("orchestrator.pipeline_driver.vendor_adapter.invoke", new_callable=AsyncMock):
        await driver.run(
            raw_message=_RAW_MESSAGE,
            user_sub=_USER_SUB,
            session_id=_SESSION_ID,
            correlation_id=uuid4(),
            source_ip=_SOURCE_IP,
        )

    driver._classifier.classify.assert_not_called()  # type: ignore[attr-defined]


async def test_bouncer_escalate_returns_human_review_message() -> None:
    """Haiku flags message as harmful (escalate=True, allowed=True) → pipeline stops."""
    driver, _ = await make_driver(bounce_result=make_bounce(allowed=True, escalate=True))

    with patch("orchestrator.pipeline_driver.vendor_adapter.invoke", new_callable=AsyncMock):
        result = await driver.run(
            raw_message=_RAW_MESSAGE,
            user_sub=_USER_SUB,
            session_id=_SESSION_ID,
            correlation_id=uuid4(),
            source_ip=_SOURCE_IP,
        )

    assert "human review" in result.lower()


async def test_bouncer_escalate_skips_classifier() -> None:
    """When Bouncer escalates, Classifier must not be called."""
    driver, _ = await make_driver(bounce_result=make_bounce(allowed=True, escalate=True))

    with patch("orchestrator.pipeline_driver.vendor_adapter.invoke", new_callable=AsyncMock):
        await driver.run(
            raw_message=_RAW_MESSAGE,
            user_sub=_USER_SUB,
            session_id=_SESSION_ID,
            correlation_id=uuid4(),
            source_ip=_SOURCE_IP,
        )

    driver._classifier.classify.assert_not_called()  # type: ignore[attr-defined]


# =============================================================================
# Classifier escalation
# =============================================================================


async def test_classifier_escalate_returns_human_review_message() -> None:
    driver, _ = await make_driver(intent_result=make_intent(escalate=True))

    with patch("orchestrator.pipeline_driver.vendor_adapter.invoke", new_callable=AsyncMock):
        result = await driver.run(
            raw_message=_RAW_MESSAGE,
            user_sub=_USER_SUB,
            session_id=_SESSION_ID,
            correlation_id=uuid4(),
            source_ip=_SOURCE_IP,
        )

    assert "human review" in result.lower()


async def test_classifier_escalate_skips_strategist() -> None:
    driver, _ = await make_driver(intent_result=make_intent(escalate=True))

    with patch("orchestrator.pipeline_driver.vendor_adapter.invoke", new_callable=AsyncMock):
        await driver.run(
            raw_message=_RAW_MESSAGE,
            user_sub=_USER_SUB,
            session_id=_SESSION_ID,
            correlation_id=uuid4(),
            source_ip=_SOURCE_IP,
        )

    driver._strategist.route.assert_not_called()  # type: ignore[attr-defined]


# =============================================================================
# Policy blocking
# =============================================================================


async def test_policy_blocked_returns_compliance_message() -> None:
    driver, _ = await make_driver(plan_result=make_plan(blocked=True))

    with patch("orchestrator.pipeline_driver.vendor_adapter.invoke", new_callable=AsyncMock):
        result = await driver.run(
            raw_message=_RAW_MESSAGE,
            user_sub=_USER_SUB,
            session_id=_SESSION_ID,
            correlation_id=uuid4(),
            source_ip=_SOURCE_IP,
        )

    assert "compliance" in result.lower()


# =============================================================================
# Error handling
# =============================================================================


async def test_presidio_error_returns_unavailable_message() -> None:
    driver, _ = await make_driver(presidio_raises=PresidioError("sidecar down"))

    with patch("orchestrator.pipeline_driver.vendor_adapter.invoke", new_callable=AsyncMock):
        result = await driver.run(
            raw_message=_RAW_MESSAGE,
            user_sub=_USER_SUB,
            session_id=_SESSION_ID,
            correlation_id=uuid4(),
            source_ip=_SOURCE_IP,
        )

    assert "temporarily unavailable" in result.lower()


async def test_unexpected_error_returns_error_message() -> None:
    driver, _ = await make_driver()
    # Make the bouncer raise an unexpected exception
    driver._bouncer.bounce = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[attr-defined]

    with patch("orchestrator.pipeline_driver.vendor_adapter.invoke", new_callable=AsyncMock):
        result = await driver.run(
            raw_message=_RAW_MESSAGE,
            user_sub=_USER_SUB,
            session_id=_SESSION_ID,
            correlation_id=uuid4(),
            source_ip=_SOURCE_IP,
        )

    assert "unexpected error" in result.lower()


# =============================================================================
# Audit guarantees
# =============================================================================


async def test_audit_runs_on_success() -> None:
    driver, _ = await make_driver()

    with patch(
        "orchestrator.pipeline_driver.vendor_adapter.invoke",
        new_callable=AsyncMock,
        return_value=_VENDOR_RESPONSE_CLEAN,
    ):
        await driver.run(
            raw_message=_RAW_MESSAGE,
            user_sub=_USER_SUB,
            session_id=_SESSION_ID,
            correlation_id=uuid4(),
            source_ip=_SOURCE_IP,
        )

    driver._audit.write.assert_called_once()  # type: ignore[attr-defined]


async def test_audit_runs_on_exception() -> None:
    """Even on unexpected exceptions, audit.write must be called."""
    driver, _ = await make_driver()
    # Trigger an unexpected exception inside the try block
    driver._bouncer.bounce = AsyncMock(side_effect=ValueError("unexpected"))  # type: ignore[attr-defined]

    with patch("orchestrator.pipeline_driver.vendor_adapter.invoke", new_callable=AsyncMock):
        await driver.run(
            raw_message=_RAW_MESSAGE,
            user_sub=_USER_SUB,
            session_id=_SESSION_ID,
            correlation_id=uuid4(),
            source_ip=_SOURCE_IP,
        )

    # audit.write is called from the finally block only when envelope is not None.
    # Since Presidio succeeds, envelope is built, so write must be called.
    driver._audit.write.assert_called_once()  # type: ignore[attr-defined]


# =============================================================================
# Vault cleanup
# =============================================================================


async def test_vault_cleanup_runs_on_success() -> None:
    """After a successful run, vault keys for the correlation_id are deleted."""
    driver, redis = await make_driver()
    cid = uuid4()
    cid_str = str(cid)

    # Pre-store a vault token
    await driver._vault.store(cid_str, {"VAULT_CLEANUP_TEST": "original_value"})

    # Confirm the key exists before the run
    keys_before = [k async for k in redis.scan_iter(f"vault:{cid_str}:*")]
    assert len(keys_before) == 1

    with patch(
        "orchestrator.pipeline_driver.vendor_adapter.invoke",
        new_callable=AsyncMock,
        return_value="clean response",
    ):
        await driver.run(
            raw_message=_RAW_MESSAGE,
            user_sub=_USER_SUB,
            session_id=_SESSION_ID,
            correlation_id=cid,
            source_ip=_SOURCE_IP,
        )

    # Vault keys must be gone after the run
    keys_after = [k async for k in redis.scan_iter(f"vault:{cid_str}:*")]
    assert keys_after == []


async def test_vault_cleanup_runs_on_presidio_error() -> None:
    """Vault.delete must run even when PresidioError is raised."""
    driver, redis = await make_driver(presidio_raises=PresidioError("down"))
    cid = uuid4()
    cid_str = str(cid)

    # Pre-store a key (simulating a previous partial run)
    await driver._vault.store(cid_str, {"VAULT_ERR_TOKEN": "value"})

    with patch("orchestrator.pipeline_driver.vendor_adapter.invoke", new_callable=AsyncMock):
        await driver.run(
            raw_message=_RAW_MESSAGE,
            user_sub=_USER_SUB,
            session_id=_SESSION_ID,
            correlation_id=cid,
            source_ip=_SOURCE_IP,
        )

    # Even on PresidioError, vault.delete runs in finally
    keys_after = [k async for k in redis.scan_iter(f"vault:{cid_str}:*")]
    assert keys_after == []


# =============================================================================
# Envelope invariants
# =============================================================================


async def test_raw_message_not_in_envelope() -> None:
    """The raw message must never appear in the envelope's redacted_message."""
    raw = "SECRET PII DATA"
    redacted = "CLEAN OUTPUT"
    driver, _ = await make_driver(
        presidio_redaction=make_redaction_result(
            redacted=redacted, was_redacted=True, entity_types=(EntityType.SG_NRIC,), entity_count=1
        ),
        vendor_response="result",
    )

    captured_envelopes: list[PipelineEnvelope] = []

    async def capture_bounce(envelope: PipelineEnvelope) -> BounceResult:
        captured_envelopes.append(envelope)
        return make_bounce()

    driver._bouncer.bounce = capture_bounce  # type: ignore[attr-defined]

    with patch(
        "orchestrator.pipeline_driver.vendor_adapter.invoke",
        new_callable=AsyncMock,
        return_value="result",
    ):
        await driver.run(
            raw_message=raw,
            user_sub=_USER_SUB,
            session_id=_SESSION_ID,
            correlation_id=uuid4(),
            source_ip=_SOURCE_IP,
        )

    assert len(captured_envelopes) == 1
    envelope = captured_envelopes[0]
    assert envelope.redacted_message == redacted
    assert raw not in envelope.redacted_message


async def test_envelope_has_hashed_raw_message() -> None:
    """Envelope must carry the SHA-256 hash of the raw message."""
    raw = "hash me please"
    expected_hash = hashlib.sha256(raw.encode()).hexdigest()
    driver, _ = await make_driver(
        presidio_redaction=make_redaction_result(
            redacted="CLEAN", was_redacted=False, entity_types=(), entity_count=0
        ),
        vendor_response="ok",
    )

    captured_envelopes: list[PipelineEnvelope] = []

    async def capture_bounce(envelope: PipelineEnvelope) -> BounceResult:
        captured_envelopes.append(envelope)
        return make_bounce()

    driver._bouncer.bounce = capture_bounce  # type: ignore[attr-defined]

    with patch(
        "orchestrator.pipeline_driver.vendor_adapter.invoke",
        new_callable=AsyncMock,
        return_value="ok",
    ):
        await driver.run(
            raw_message=raw,
            user_sub=_USER_SUB,
            session_id=_SESSION_ID,
            correlation_id=uuid4(),
            source_ip=_SOURCE_IP,
        )

    assert len(captured_envelopes) == 1
    assert captured_envelopes[0].raw_message_hash == expected_hash
