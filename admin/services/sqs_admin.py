"""SQS operations for the escalation queue.

Reads pending messages from the escalation queue for human review.
Approve: removes from escalation queue and marks approved in review_log.
Reject: sends to DLQ by deleting without acting (SQS DLQ redrive handles it
        after maxReceiveCount is exceeded; for explicit reject we delete immediately).
Requeue: extends visibility timeout to 0 and adds an annotation in review_log.

IAM note: the admin role explicitly denies sqs:SendMessage on the *incoming* queue.
Approve does NOT re-enqueue to the incoming queue — it marks status in review_log
and the orchestrator can poll for approved records in a future iteration.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import aioboto3  # type: ignore[import-untyped]

from admin.models import EscalationAction, EscalationList, EscalationMessage
from shared.logging import safe_log


class SQSAdminService:
    def __init__(
        self,
        escalation_url: str,
        review_table: str,
        region: str,
        visibility_seconds: int = 300,
    ) -> None:
        self._queue_url = escalation_url
        self._review_table = review_table
        self._region = region
        self._vis = visibility_seconds
        self._session: aioboto3.Session = aioboto3.Session()

    async def list_pending(self, max_messages: int = 10) -> EscalationList:
        """Receive up to max_messages from the escalation queue.

        Messages are held invisible for visibility_seconds so another admin
        action doesn't double-process them. The caller must approve/reject
        within that window or the message becomes visible again.
        """
        if not self._queue_url:
            return EscalationList(messages=[], queue_depth=0)

        try:
            async with self._session.client("sqs", region_name=self._region) as sqs:
                # Get approximate depth first
                attr_resp = await sqs.get_queue_attributes(
                    QueueUrl=self._queue_url,
                    AttributeNames=["ApproximateNumberOfMessages"],
                )
                depth = int(
                    attr_resp["Attributes"].get("ApproximateNumberOfMessages", "0")
                )

                resp = await sqs.receive_message(
                    QueueUrl=self._queue_url,
                    MaxNumberOfMessages=min(max_messages, 10),
                    VisibilityTimeout=self._vis,
                    WaitTimeSeconds=1,
                    AttributeNames=["ApproximateReceiveCount", "SentTimestamp"],
                    MessageAttributeNames=["All"],
                )

            raw_messages: list[dict[str, Any]] = resp.get("Messages", [])
            messages = [self._parse_message(m) for m in raw_messages]
            return EscalationList(
                messages=[m for m in messages if m is not None], queue_depth=depth
            )

        except Exception as exc:
            safe_log.warning("admin.sqs.list_error", error_type=type(exc).__name__)
            return EscalationList(messages=[], queue_depth=0)

    def _parse_message(self, raw: dict[str, Any]) -> EscalationMessage | None:
        try:
            body = json.loads(raw.get("Body", "{}"))
            attrs = raw.get("Attributes", {})
            sent_ts = attrs.get("SentTimestamp")
            sent_at = (
                datetime.fromtimestamp(int(sent_ts) / 1000, tz=UTC)
                if sent_ts else None
            )
            return EscalationMessage(
                receipt_handle=raw["ReceiptHandle"],
                message_id=raw["MessageId"],
                correlation_id=body.get("correlation_id", ""),
                user_sub=body.get("user_sub", ""),
                session_id=body.get("session_id", ""),
                # Only the redacted preview — never raw message
                redacted_preview=body.get("redacted_message", ""),
                entity_types=body.get("entity_types", []),
                bouncer_reason=body.get("bouncer_reason"),
                sent_at=sent_at,
                approximate_receive_count=int(attrs.get("ApproximateReceiveCount", 0)),
            )
        except Exception as exc:
            safe_log.warning("admin.sqs.parse_error", error_type=type(exc).__name__)
            return None

    async def approve(self, receipt_handle: str, correlation_id: str) -> EscalationAction:
        """Mark approved in review_log, then delete from escalation queue.

        Does NOT re-enqueue to the incoming SQS queue (admin IAM denies that).
        The orchestrator polls review_log for approved=True records.
        """
        await self._update_review_log(correlation_id, status="approved", annotation=None)
        await self._delete_message(receipt_handle)
        safe_log.info("admin.escalation.approved", correlation_id=correlation_id)
        return EscalationAction(
            message_id="",
            action="approved",
            correlation_id=correlation_id,
            annotation=None,
        )

    async def reject(self, receipt_handle: str, correlation_id: str) -> EscalationAction:
        """Mark rejected in review_log, then delete from queue (moves to DLQ via policy)."""
        await self._update_review_log(correlation_id, status="rejected", annotation=None)
        await self._delete_message(receipt_handle)
        safe_log.info("admin.escalation.rejected", correlation_id=correlation_id)
        return EscalationAction(
            message_id="",
            action="rejected",
            correlation_id=correlation_id,
            annotation=None,
        )

    async def requeue(
        self, receipt_handle: str, correlation_id: str, annotation: str
    ) -> EscalationAction:
        """Make the message visible again immediately so it re-appears for review."""
        await self._update_review_log(correlation_id, status="requeued", annotation=annotation)
        try:
            async with self._session.client("sqs", region_name=self._region) as sqs:
                await sqs.change_message_visibility(
                    QueueUrl=self._queue_url,
                    ReceiptHandle=receipt_handle,
                    VisibilityTimeout=0,
                )
        except Exception as exc:
            safe_log.warning("admin.sqs.requeue_error", error_type=type(exc).__name__)
        safe_log.info("admin.escalation.requeued", correlation_id=correlation_id)
        return EscalationAction(
            message_id="",
            action="requeued",
            correlation_id=correlation_id,
            annotation=annotation,
        )

    async def _delete_message(self, receipt_handle: str) -> None:
        try:
            async with self._session.client("sqs", region_name=self._region) as sqs:
                await sqs.delete_message(
                    QueueUrl=self._queue_url, ReceiptHandle=receipt_handle
                )
        except Exception as exc:
            safe_log.warning("admin.sqs.delete_error", error_type=type(exc).__name__)

    async def _update_review_log(
        self, correlation_id: str, status: str, annotation: str | None
    ) -> None:
        try:
            async with self._session.resource("dynamodb", region_name=self._region) as dynamo:
                table = await dynamo.Table(self._review_table)
                update_expr = "SET #s = :s, reviewed_at = :t"
                expr_values: dict[str, Any] = {
                    ":s": status,
                    ":t": datetime.now(UTC).isoformat(),
                }
                if annotation:
                    update_expr += ", annotation = :a"
                    expr_values[":a"] = annotation
                await table.update_item(
                    Key={"correlation_id": correlation_id},
                    UpdateExpression=update_expr,
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues=expr_values,
                )
        except Exception as exc:
            safe_log.warning("admin.dynamo.review_log_error", error_type=type(exc).__name__)
