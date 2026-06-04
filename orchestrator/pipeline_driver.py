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

import asyncio
import hashlib
import json
import time
from datetime import UTC, datetime
from uuid import UUID

import aioboto3  # type: ignore[import-untyped]
import redis.asyncio as aioredis

import adapters.litellm_adapter as vendor_adapter
from bouncer.bouncer import Bouncer
from classifier.classifier import Classifier
from orchestrator.audit import AuditLogger
from orchestrator.history import SessionHistory
from orchestrator.presidio_client import PresidioClient
from orchestrator.vault import TokenVault
from shared.errors import PresidioError
from shared.logging import safe_log
from shared.metrics import emit_classifier, emit_strategist
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
        history: SessionHistory,
        vault_ttl_seconds: int = 300,
        sqs_escalation_url: str = "",
        aws_region: str = "ap-southeast-1",
    ) -> None:
        self._presidio = presidio
        self._vault = TokenVault(redis, ttl_seconds=vault_ttl_seconds)
        self._bouncer = bouncer
        self._classifier = classifier
        self._strategist = strategist
        self._audit = audit
        self._history = history
        self._sqs_escalation_url = sqs_escalation_url
        self._aws_region = aws_region
        self._sqs_session: aioboto3.Session = aioboto3.Session()

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
            if bounce.escalate:
                safe_log.info(
                    "pipeline.escalated",
                    reason=bounce.reason,
                    confidence=bounce.confidence,
                    escalate=True,
                )
                await self._send_escalation(envelope, bounce)
                return "Your request has been sent for human review."

            # Step 6: Classifier — load history first for follow-up detection
            history_turns = await self._history.get(session_id)
            intent = await self._classifier.classify(envelope, history=history_turns or None)
            asyncio.create_task(emit_classifier(intent, envelope.bedrock_region))
            if intent.escalate:
                safe_log.info(
                    "pipeline.escalated",
                    intent=intent.intent,
                    confidence=intent.confidence,
                    escalate=True,
                )
                await self._send_escalation(envelope, bounce)
                return "Your request has been sent for human review."

            # Step 7: Strategist
            plan = await self._strategist.route(envelope, intent)
            asyncio.create_task(emit_strategist(plan, envelope.bedrock_region))
            if plan.blocked:
                safe_log.info("pipeline.policy_blocked", blocked=True)
                return "This request cannot be processed due to compliance restrictions."

            # Step 8: Vendor adapter — pass history for multi-turn context
            vendor_response = await vendor_adapter.invoke(
                envelope, plan, history=history_turns or None
            )

            # Persist the exchange (vault-tokenized form, before restore) so
            # future turns can reference prior context without exposing raw PII.
            await self._history.append(
                session_id, envelope.redacted_message, vendor_response
            )

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

    async def _send_escalation(
        self,
        envelope: PipelineEnvelope,
        bounce: BounceResult | None,
    ) -> None:
        if not self._sqs_escalation_url:
            safe_log.warning("pipeline.escalation.no_queue_url")
            return
        payload = json.dumps({
            "correlation_id": str(envelope.correlation_id),
            "user_sub": envelope.user_sub,
            "session_id": envelope.session_id,
            "redacted_message": envelope.redacted_message,
            "entity_types": list(envelope.entity_types_redacted),
            "bouncer_reason": bounce.reason if bounce else None,
        })
        try:
            async with self._sqs_session.client("sqs", region_name=self._aws_region) as sqs:
                await sqs.send_message(
                    QueueUrl=self._sqs_escalation_url,
                    MessageBody=payload,
                )
            safe_log.info(
                "pipeline.escalation.sent",
                correlation_id=str(envelope.correlation_id),
            )
        except Exception as exc:
            safe_log.warning("pipeline.escalation.send_error", error_type=type(exc).__name__)
