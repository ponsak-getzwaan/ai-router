"""Pipeline driver: the canonical end-to-end request sequence.

Sequence (matches architecture.md §"End-to-end request sequence"):
  1. Set correlation_id ContextVar (done in sqs_consumer before calling here)
  2. Presidio anonymize
  3. Store tokens in Redis vault
  4. Build PipelineEnvelope (raw message hashed and discarded)
  5. Bouncer
  6. Classifier
  7. Strategist
  8. Vendor adapter
  9. Restore de-redacted response
  10. Audit log (finally block — runs on success AND failure)
  11. Vault cleanup (finally block)

Non-negotiables enforced here:
  - Raw message never leaves this function (only redacted_message flows down)
  - Audit runs in finally regardless of exception
  - Vault cleanup runs in finally regardless of exception
"""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime
from uuid import UUID

import redis.asyncio as aioredis

import adapters.litellm_adapter as vendor_adapter
from bouncer.bouncer import Bouncer
from classifier.classifier import Classifier
from orchestrator.audit import AuditLogger
from orchestrator.presidio_client import PresidioClient
from orchestrator.vault import TokenVault
from shared.errors import PresidioError
from shared.logging import safe_log
from shared.models import (
    BounceResult,
    ClassifiedIntent,
    PipelineEnvelope,
    RoutingPlan,
)
from strategist.strategist import Strategist


class PipelineDriver:
    def __init__(
        self,
        presidio: PresidioClient,
        redis: aioredis.Redis,
        bouncer: Bouncer,
        classifier: Classifier,
        strategist: Strategist,
        audit: AuditLogger,
        vault_ttl_seconds: int = 300,
    ) -> None:
        self._presidio = presidio
        self._vault = TokenVault(redis, ttl_seconds=vault_ttl_seconds)
        self._bouncer = bouncer
        self._classifier = classifier
        self._strategist = strategist
        self._audit = audit

    async def run(
        self,
        raw_message: str,
        user_sub: str,
        session_id: str,
        correlation_id: UUID,
        source_ip: str,
        tokens: dict[str, str] | None = None,
    ) -> str:
        """Drive one request through the full pipeline.

        Args:
            raw_message:    The original, unredacted user message.
            tokens:         Token→original mapping from Presidio (if pre-computed).
                            If None, Presidio is called to compute it.

        Returns:
            The de-redacted vendor response string.
        """
        start = time.monotonic()
        cid_str = str(correlation_id)

        bounce: BounceResult | None = None
        intent: ClassifiedIntent | None = None
        plan: RoutingPlan | None = None
        vendor_response: str | None = None
        error_type: str | None = None
        envelope: PipelineEnvelope | None = None

        try:
            # Step 2-3: Redaction + vault
            redaction = await self._presidio.anonymize(raw_message, cid_str)
            if tokens:
                await self._vault.store(cid_str, tokens)

            # Step 4: Build PipelineEnvelope — raw message is hashed and discarded
            raw_hash = hashlib.sha256(raw_message.encode()).hexdigest()
            envelope = PipelineEnvelope(
                correlation_id=correlation_id,
                user_sub=user_sub,
                session_id=session_id,
                redacted_message=redaction.redacted_message,
                raw_message_hash=raw_hash,
                entity_types_redacted=redaction.entity_types_found,
                entity_count=redaction.entity_count,
                was_redacted=redaction.was_redacted,
                timestamp=datetime.now(UTC),
                bedrock_region="ap-southeast-1",
                source_ip=source_ip,
            )
            # raw_message is no longer referenced after this point

            # Step 5: Bouncer
            bounce = await self._bouncer.bounce(envelope)
            if not bounce.allowed:
                safe_log.info(
                    "pipeline.blocked",
                    allowed=False,
                    reason=bounce.reason,
                    layer=bounce.layer,
                )
                return "Your request cannot be processed at this time."

            # Step 6: Classifier
            intent = await self._classifier.classify(envelope)
            if intent.escalate:
                safe_log.info(
                    "pipeline.escalated",
                    intent=intent.intent,
                    confidence=intent.confidence,
                    escalate=True,
                )
                return "Your request has been sent for human review."

            # Step 7: Strategist
            plan = await self._strategist.route(envelope, intent)
            if plan.blocked:
                safe_log.info("pipeline.policy_blocked", blocked=True)
                return "This request cannot be processed due to compliance restrictions."

            # Step 8: Vendor adapter
            vendor_response = await vendor_adapter.invoke(envelope, plan)

            # Step 9: De-redact — restore tokens in the vendor response
            restored = await self._vault.restore(cid_str, vendor_response)
            return restored

        except PresidioError as exc:
            error_type = type(exc).__name__
            safe_log.warning("pipeline.presidio_error", error_type=error_type)
            return "Service temporarily unavailable. Please try again."

        except Exception as exc:
            error_type = type(exc).__name__
            safe_log.warning("pipeline.unexpected_error", error_type=error_type)
            return "An unexpected error occurred."

        finally:
            # Step 10: Audit — always runs
            if envelope is not None:
                await self._audit.write(
                    envelope=envelope,
                    bounce=bounce,
                    intent=intent,
                    plan=plan,
                    vendor_response=vendor_response,
                    start_time=start,
                    error_type=error_type,
                )

            # Step 11: Vault cleanup — always runs
            await self._vault.delete(cid_str)
