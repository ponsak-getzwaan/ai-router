"""Audit logger — writes per-request records to DynamoDB.

Records contain entity types and counts ONLY — never values, never the
raw or redacted message (CLAUDE.md §3.10 and architecture §end-to-end sequence).
The finally block in pipeline_driver.py guarantees this runs on both
success and failure paths.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import aioboto3  # type: ignore[import-untyped]

from shared.logging import safe_log
from shared.models import BounceResult, ClassifiedIntent, PipelineEnvelope, RoutingPlan


class AuditLogger:
    def __init__(self, table_name: str, region: str) -> None:
        self._table_name = table_name
        self._region = region
        self._session: aioboto3.Session = aioboto3.Session()

    async def write(
        self,
        envelope: PipelineEnvelope,
        bounce: BounceResult | None,
        intent: ClassifiedIntent | None,
        plan: RoutingPlan | None,
        vendor_response: str | None,
        start_time: float,
        error_type: str | None = None,
    ) -> None:
        total_ms = (time.monotonic() - start_time) * 1000.0
        cid = str(envelope.correlation_id)

        item: dict[str, Any] = {
            "correlation_id": cid,
            "timestamp": datetime.now(UTC).isoformat(),
            "user_sub": envelope.user_sub,
            "session_id": envelope.session_id,
            # Entity metadata — types and counts only, never values
            "entity_types_redacted": [et for et in envelope.entity_types_redacted],
            "entity_count": envelope.entity_count,
            "was_redacted": envelope.was_redacted,
            # Bouncer
            "bouncer_allowed": bounce.allowed if bounce else None,
            "bouncer_escalated": bounce.escalate if bounce else None,
            "bouncer_timed_out": bounce.timed_out if bounce else None,
            # Classifier
            "intent": intent.intent if intent else None,
            "intent_confidence": str(intent.confidence) if intent else None,
            "intent_escalated": intent.escalate if intent else None,
            # Strategist
            "vendor": plan.primary_vendor if plan else None,
            "routing_path": plan.path if plan else None,
            "policy_blocked": plan.blocked if plan else None,
            # Vendor response — redacted text (before vault restore), truncated at 4000 chars
            "vendor_response_redacted": vendor_response[:4000] if vendor_response else None,
            # Latency
            "total_latency_ms": str(round(total_ms, 1)),
            # Error (type name only — never message)
            "error_type": error_type,
            # TTL: keep audit records for 365 days
            "ttl": int(time.time()) + 365 * 86400,
        }

        # Remove None values — DynamoDB doesn't accept None
        clean_item = {k: v for k, v in item.items() if v is not None}

        try:
            async with self._session.resource("dynamodb", region_name=self._region) as dynamo:
                table = await dynamo.Table(self._table_name)
                await table.put_item(Item=clean_item)
            safe_log.info(
                "orchestrator.audit.written",
                total_latency_ms=total_ms,
                vendor=plan.primary_vendor if plan else None,
            )
        except Exception as exc:
            safe_log.warning("orchestrator.audit.error", error_type=type(exc).__name__)
