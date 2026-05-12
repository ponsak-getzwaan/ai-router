"""SQS consumer: dequeues messages and drives the pipeline.

The correlation_id ContextVar is set HERE as the very first action when a
message is dequeued — before any pipeline code runs (CLAUDE.md §7 Orchestrator).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID

import aioboto3  # type: ignore[import-untyped]

from orchestrator.config import OrchestratorConfig
from orchestrator.pipeline_driver import PipelineDriver
from shared.correlation import new_correlation_id, set_correlation_id
from shared.logging import safe_log


class SQSConsumer:
    def __init__(
        self,
        config: OrchestratorConfig,
        driver: PipelineDriver,
    ) -> None:
        self._config = config
        self._driver = driver
        self._session: aioboto3.Session = aioboto3.Session()
        self._running = False

    async def start(self) -> None:
        """Run the polling loop until stop() is called."""
        self._running = True
        safe_log.info("orchestrator.consumer.started")
        async with self._session.client("sqs", region_name=self._config.aws_region) as sqs:
            while self._running:
                await self._poll(sqs)

    async def stop(self) -> None:
        self._running = False
        safe_log.info("orchestrator.consumer.stopped")

    async def _poll(self, sqs: Any) -> None:
        try:
            response = await sqs.receive_message(
                QueueUrl=self._config.sqs_incoming_url,
                MaxNumberOfMessages=self._config.sqs_max_messages,
                WaitTimeSeconds=self._config.sqs_poll_wait_seconds,
                AttributeNames=["All"],
                MessageAttributeNames=["All"],
            )
        except Exception as exc:
            safe_log.warning("orchestrator.sqs.poll_error", error_type=type(exc).__name__)
            await asyncio.sleep(5)
            return

        messages: list[dict[str, Any]] = response.get("Messages", [])
        if not messages:
            return

        tasks = [asyncio.create_task(self._handle(sqs, msg)) for msg in messages]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _handle(self, sqs: Any, message: dict[str, Any]) -> None:
        receipt = message["ReceiptHandle"]

        # Set correlation_id as the FIRST action — before any pipeline code.
        try:
            body: dict[str, Any] = json.loads(message.get("Body", "{}"))
            cid_raw = body.get("correlation_id")
            correlation_id: UUID = UUID(cid_raw) if cid_raw else new_correlation_id()
        except (ValueError, KeyError):
            correlation_id = new_correlation_id()

        set_correlation_id(correlation_id)

        safe_log.info("orchestrator.message.received", session_id=body.get("session_id", ""))

        try:
            raw_message: str = body.get("message", "")
            user_sub: str = body.get("user_sub", "unknown")
            session_id: str = body.get("session_id", str(correlation_id))
            source_ip: str = body.get("source_ip", "0.0.0.0")
            tokens: dict[str, str] | None = body.get("tokens")

            await self._driver.run(
                raw_message=raw_message,
                user_sub=user_sub,
                session_id=session_id,
                correlation_id=correlation_id,
                source_ip=source_ip,
                tokens=tokens,
            )

            # Delete the message only on success
            await sqs.delete_message(
                QueueUrl=self._config.sqs_incoming_url,
                ReceiptHandle=receipt,
            )

        except Exception as exc:
            safe_log.warning(
                "orchestrator.message.failed",
                error_type=type(exc).__name__,
                session_id=body.get("session_id", ""),
            )
            # Do NOT delete — message returns to queue and eventually hits DLQ
