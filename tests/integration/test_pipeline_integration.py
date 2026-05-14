"""Integration tests for PipelineDriver.run().

Uses:
- Real fakeredis vault (store/restore/delete operations actually execute)
- Mocked Presidio, Bouncer, Classifier, Strategist, AuditLogger, vendor adapter
- Validates pipeline orchestration invariants:
    * Vault cleanup runs in finally (success AND failure paths)
    * Audit runs in finally (success AND failure paths)
    * Bouncer block short-circuits classifier and strategist
    * Classifier escalation short-circuits strategist
    * Raw message never propagates past redaction
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from shared.errors import PresidioError
from shared.models import BounceResult, BouncerLayer
from tests.integration.conftest import (
    make_bounce_result,
    make_intent_result,
    make_redaction_result,
    make_routing_plan,
)

CID = uuid4()
USER_SUB = "user-sub-test"
SESSION_ID = "session-integration-001"
SOURCE_IP = "10.0.1.5"
RAW_MESSAGE = "What is my NRIC S1234567D status?"


@pytest.mark.integration
class TestPipelineHappyPath:
    async def test_returns_vendor_response(self, driver) -> None:
        with patch("adapters.litellm_adapter.invoke", new=AsyncMock(return_value="All good.")):
            result = await driver.run(
                raw_message=RAW_MESSAGE,
                user_sub=USER_SUB,
                session_id=SESSION_ID,
                correlation_id=CID,
                source_ip=SOURCE_IP,
            )
        assert result == "All good."

    async def test_vault_tokens_restored_in_response(self, driver, redis_client) -> None:
        """Store a token in vault beforehand; verify it's restored in the response."""
        cid_str = str(CID)
        await redis_client.set(f"vault:{cid_str}:VAULT_3A4B5C", "S1234567D", ex=300)

        # Vendor "responds" with the vault token — driver should restore it
        with patch(
            "adapters.litellm_adapter.invoke",
            new=AsyncMock(return_value="Your status for VAULT_3A4B5C is active."),
        ):
            result = await driver.run(
                raw_message=RAW_MESSAGE,
                user_sub=USER_SUB,
                session_id=SESSION_ID,
                correlation_id=CID,
                source_ip=SOURCE_IP,
            )
        assert "S1234567D" in result
        assert "VAULT_3A4B5C" not in result

    async def test_vault_cleaned_up_after_success(self, driver, redis_client) -> None:
        """Vault keys must be deleted in the finally block on success."""
        cid_str = str(CID)
        await redis_client.set(f"vault:{cid_str}:VAULT_AABBCC", "original_value", ex=300)

        with patch("adapters.litellm_adapter.invoke", new=AsyncMock(return_value="Done.")):
            await driver.run(
                raw_message=RAW_MESSAGE,
                user_sub=USER_SUB,
                session_id=SESSION_ID,
                correlation_id=CID,
                source_ip=SOURCE_IP,
            )

        remaining = [key async for key in redis_client.scan_iter(f"vault:{cid_str}:*")]
        assert remaining == []

    async def test_audit_called_on_success(self, driver, mock_audit) -> None:
        with patch("adapters.litellm_adapter.invoke", new=AsyncMock(return_value="OK")):
            await driver.run(
                raw_message=RAW_MESSAGE,
                user_sub=USER_SUB,
                session_id=SESSION_ID,
                correlation_id=CID,
                source_ip=SOURCE_IP,
            )
        mock_audit.write.assert_called_once()


@pytest.mark.integration
class TestPipelineBouncerBlock:
    async def test_bouncer_block_returns_rejection_message(self, driver, mock_bouncer) -> None:
        mock_bouncer.bounce = AsyncMock(
            return_value=make_bounce_result(allowed=False, reason="banned_user")
        )
        result = await driver.run(
            raw_message=RAW_MESSAGE,
            user_sub=USER_SUB,
            session_id=SESSION_ID,
            correlation_id=CID,
            source_ip=SOURCE_IP,
        )
        assert "cannot be processed" in result.lower()

    async def test_bouncer_block_skips_classifier(self, driver, mock_bouncer, mock_classifier) -> None:
        mock_bouncer.bounce = AsyncMock(
            return_value=make_bounce_result(allowed=False, reason="content_policy")
        )
        await driver.run(
            raw_message=RAW_MESSAGE,
            user_sub=USER_SUB,
            session_id=SESSION_ID,
            correlation_id=CID,
            source_ip=SOURCE_IP,
        )
        mock_classifier.classify.assert_not_called()

    async def test_bouncer_block_skips_strategist(self, driver, mock_bouncer, mock_strategist) -> None:
        mock_bouncer.bounce = AsyncMock(
            return_value=make_bounce_result(allowed=False, reason="banned_user")
        )
        await driver.run(
            raw_message=RAW_MESSAGE,
            user_sub=USER_SUB,
            session_id=SESSION_ID,
            correlation_id=CID,
            source_ip=SOURCE_IP,
        )
        mock_strategist.route.assert_not_called()

    async def test_vault_cleaned_up_after_bouncer_block(
        self, driver, mock_bouncer, redis_client
    ) -> None:
        """Vault cleanup must run even when bouncer blocks the request."""
        cid_str = str(CID)
        await redis_client.set(f"vault:{cid_str}:VAULT_XYZXYZ", "original", ex=300)

        mock_bouncer.bounce = AsyncMock(
            return_value=make_bounce_result(allowed=False, reason="banned_user")
        )
        await driver.run(
            raw_message=RAW_MESSAGE,
            user_sub=USER_SUB,
            session_id=SESSION_ID,
            correlation_id=CID,
            source_ip=SOURCE_IP,
        )
        remaining = [key async for key in redis_client.scan_iter(f"vault:{cid_str}:*")]
        assert remaining == []

    async def test_audit_called_after_bouncer_block(self, driver, mock_bouncer, mock_audit) -> None:
        mock_bouncer.bounce = AsyncMock(
            return_value=make_bounce_result(allowed=False, reason="content_policy")
        )
        await driver.run(
            raw_message=RAW_MESSAGE,
            user_sub=USER_SUB,
            session_id=SESSION_ID,
            correlation_id=CID,
            source_ip=SOURCE_IP,
        )
        mock_audit.write.assert_called_once()


@pytest.mark.integration
class TestPipelineClassifierEscalation:
    async def test_escalation_returns_review_message(self, driver, mock_classifier) -> None:
        mock_classifier.classify = AsyncMock(return_value=make_intent_result(escalate=True))
        result = await driver.run(
            raw_message=RAW_MESSAGE,
            user_sub=USER_SUB,
            session_id=SESSION_ID,
            correlation_id=CID,
            source_ip=SOURCE_IP,
        )
        assert "human review" in result.lower()

    async def test_escalation_skips_strategist(self, driver, mock_classifier, mock_strategist) -> None:
        mock_classifier.classify = AsyncMock(return_value=make_intent_result(escalate=True))
        await driver.run(
            raw_message=RAW_MESSAGE,
            user_sub=USER_SUB,
            session_id=SESSION_ID,
            correlation_id=CID,
            source_ip=SOURCE_IP,
        )
        mock_strategist.route.assert_not_called()

    async def test_vault_cleaned_up_after_escalation(
        self, driver, mock_classifier, redis_client
    ) -> None:
        cid_str = str(CID)
        await redis_client.set(f"vault:{cid_str}:VAULT_ESC001", "esc_value", ex=300)
        mock_classifier.classify = AsyncMock(return_value=make_intent_result(escalate=True))
        await driver.run(
            raw_message=RAW_MESSAGE,
            user_sub=USER_SUB,
            session_id=SESSION_ID,
            correlation_id=CID,
            source_ip=SOURCE_IP,
        )
        remaining = [key async for key in redis_client.scan_iter(f"vault:{cid_str}:*")]
        assert remaining == []

    async def test_audit_called_after_escalation(
        self, driver, mock_classifier, mock_audit
    ) -> None:
        mock_classifier.classify = AsyncMock(return_value=make_intent_result(escalate=True))
        await driver.run(
            raw_message=RAW_MESSAGE,
            user_sub=USER_SUB,
            session_id=SESSION_ID,
            correlation_id=CID,
            source_ip=SOURCE_IP,
        )
        mock_audit.write.assert_called_once()


@pytest.mark.integration
class TestPipelinePolicyBlock:
    async def test_policy_block_returns_compliance_message(
        self, driver, mock_strategist
    ) -> None:
        mock_strategist.route = AsyncMock(return_value=make_routing_plan(blocked=True))
        result = await driver.run(
            raw_message=RAW_MESSAGE,
            user_sub=USER_SUB,
            session_id=SESSION_ID,
            correlation_id=CID,
            source_ip=SOURCE_IP,
        )
        assert "compliance" in result.lower()

    async def test_audit_called_after_policy_block(
        self, driver, mock_strategist, mock_audit
    ) -> None:
        mock_strategist.route = AsyncMock(return_value=make_routing_plan(blocked=True))
        await driver.run(
            raw_message=RAW_MESSAGE,
            user_sub=USER_SUB,
            session_id=SESSION_ID,
            correlation_id=CID,
            source_ip=SOURCE_IP,
        )
        mock_audit.write.assert_called_once()


@pytest.mark.integration
class TestPipelinePresidioError:
    async def test_presidio_error_returns_unavailable_message(
        self, driver, mock_presidio
    ) -> None:
        mock_presidio.anonymize = AsyncMock(side_effect=PresidioError("timeout"))
        result = await driver.run(
            raw_message=RAW_MESSAGE,
            user_sub=USER_SUB,
            session_id=SESSION_ID,
            correlation_id=CID,
            source_ip=SOURCE_IP,
        )
        assert "unavailable" in result.lower() or "try again" in result.lower()

    async def test_presidio_error_still_cleans_vault(
        self, driver, mock_presidio, redis_client
    ) -> None:
        cid_str = str(CID)
        await redis_client.set(f"vault:{cid_str}:VAULT_PRES01", "v", ex=300)
        mock_presidio.anonymize = AsyncMock(side_effect=PresidioError("timeout"))
        await driver.run(
            raw_message=RAW_MESSAGE,
            user_sub=USER_SUB,
            session_id=SESSION_ID,
            correlation_id=CID,
            source_ip=SOURCE_IP,
        )
        remaining = [key async for key in redis_client.scan_iter(f"vault:{cid_str}:*")]
        assert remaining == []


@pytest.mark.integration
class TestPipelineUnexpectedError:
    async def test_unexpected_exception_returns_error_message(
        self, driver, mock_bouncer
    ) -> None:
        mock_bouncer.bounce = AsyncMock(side_effect=RuntimeError("boom"))
        result = await driver.run(
            raw_message=RAW_MESSAGE,
            user_sub=USER_SUB,
            session_id=SESSION_ID,
            correlation_id=CID,
            source_ip=SOURCE_IP,
        )
        assert "unexpected" in result.lower() or "error" in result.lower()

    async def test_audit_called_on_unexpected_exception(
        self, driver, mock_bouncer, mock_audit
    ) -> None:
        """Audit finally block must run even on completely unexpected errors."""
        mock_bouncer.bounce = AsyncMock(side_effect=RuntimeError("boom"))
        await driver.run(
            raw_message=RAW_MESSAGE,
            user_sub=USER_SUB,
            session_id=SESSION_ID,
            correlation_id=CID,
            source_ip=SOURCE_IP,
        )
        # Audit is called in finally — even on uncaught exceptions
        mock_audit.write.assert_called_once()

    async def test_vault_cleaned_up_on_unexpected_exception(
        self, driver, mock_bouncer, redis_client
    ) -> None:
        cid_str = str(CID)
        await redis_client.set(f"vault:{cid_str}:VAULT_EXC01", "val", ex=300)
        mock_bouncer.bounce = AsyncMock(side_effect=RuntimeError("boom"))
        await driver.run(
            raw_message=RAW_MESSAGE,
            user_sub=USER_SUB,
            session_id=SESSION_ID,
            correlation_id=CID,
            source_ip=SOURCE_IP,
        )
        remaining = [key async for key in redis_client.scan_iter(f"vault:{cid_str}:*")]
        assert remaining == []


@pytest.mark.integration
class TestPipelineAuditInvariants:
    async def test_audit_receives_correlation_id(self, driver, mock_audit) -> None:
        with patch("adapters.litellm_adapter.invoke", new=AsyncMock(return_value="OK")):
            await driver.run(
                raw_message=RAW_MESSAGE,
                user_sub=USER_SUB,
                session_id=SESSION_ID,
                correlation_id=CID,
                source_ip=SOURCE_IP,
            )
        call_kwargs = mock_audit.write.call_args.kwargs
        assert call_kwargs["envelope"].correlation_id == CID

    async def test_audit_envelope_has_no_raw_message(self, driver, mock_audit) -> None:
        """PipelineEnvelope passed to audit must never contain raw message text."""
        with patch("adapters.litellm_adapter.invoke", new=AsyncMock(return_value="OK")):
            await driver.run(
                raw_message=RAW_MESSAGE,
                user_sub=USER_SUB,
                session_id=SESSION_ID,
                correlation_id=CID,
                source_ip=SOURCE_IP,
            )
        envelope = mock_audit.write.call_args.kwargs["envelope"]
        # PipelineEnvelope must not have a raw_message field (by model definition)
        assert not hasattr(envelope, "raw_message")
        # The redacted message should contain VAULT tokens, not the raw NRIC
        assert "S1234567D" not in envelope.redacted_message

    async def test_audit_error_type_is_none_on_success(self, driver, mock_audit) -> None:
        with patch("adapters.litellm_adapter.invoke", new=AsyncMock(return_value="OK")):
            await driver.run(
                raw_message=RAW_MESSAGE,
                user_sub=USER_SUB,
                session_id=SESSION_ID,
                correlation_id=CID,
                source_ip=SOURCE_IP,
            )
        call_kwargs = mock_audit.write.call_args.kwargs
        assert call_kwargs["error_type"] is None

    async def test_audit_error_type_is_class_name_not_message(
        self, driver, mock_bouncer, mock_audit
    ) -> None:
        """Error type must be the class name only, never the exception message."""
        mock_bouncer.bounce = AsyncMock(side_effect=RuntimeError("sensitive info here"))
        await driver.run(
            raw_message=RAW_MESSAGE,
            user_sub=USER_SUB,
            session_id=SESSION_ID,
            correlation_id=CID,
            source_ip=SOURCE_IP,
        )
        call_kwargs = mock_audit.write.call_args.kwargs
        assert call_kwargs["error_type"] == "RuntimeError"
        # The exception message must never appear
        assert "sensitive" not in str(call_kwargs)
