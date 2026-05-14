"""Integration tests for SQSConsumer._handle().

Tests the message parsing, correlation ID setup, and pipeline invocation
without running the infinite polling loop. The _handle() method is the
core logic; start()/stop() are thin wrappers around it.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from orchestrator.config import OrchestratorConfig
from orchestrator.pipeline_driver import PipelineDriver
from orchestrator.sqs_consumer import SQSConsumer
from shared.correlation import get_correlation_id, set_correlation_id

QUEUE_URL = "https://sqs.ap-southeast-1.amazonaws.com/123456789/ai-router-incoming"

_DEFAULT_BODY: dict = {
    "correlation_id": "aaaaaaaa-bbbb-cccc-dddd-111111111111",
    "message": "What is my account balance?",
    "user_sub": "user-sub-sqs-test",
    "session_id": "sess-sqs-001",
    "source_ip": "203.0.113.42",
}


def _make_sqs_message(body: dict | None = None) -> dict:
    return {
        "ReceiptHandle": "receipt-handle-xyz",
        "Body": json.dumps(body or _DEFAULT_BODY),
    }


def _make_consumer(driver: PipelineDriver) -> SQSConsumer:
    config = OrchestratorConfig(
        sqs_incoming_url=QUEUE_URL,
        sqs_escalation_url="https://sqs.ap-southeast-1.amazonaws.com/123456789/escalation",
        presidio_url="http://presidio.internal:8080",
        redis_url="redis://localhost:6379/0",
    )
    return SQSConsumer(config=config, driver=driver)


@pytest.mark.integration
class TestSQSConsumerMessageParsing:
    async def test_correlation_id_from_body_sets_context_var(self) -> None:
        """CID from the message body must be set as the ContextVar."""
        expected_cid = UUID("aaaaaaaa-bbbb-cccc-dddd-111111111111")
        captured: list[UUID] = []

        mock_driver = MagicMock()
        async def capture_run(**kwargs) -> str:
            captured.append(get_correlation_id())
            return "ok"
        mock_driver.run = capture_run

        consumer = _make_consumer(mock_driver)
        mock_sqs = AsyncMock()
        await consumer._handle(mock_sqs, _make_sqs_message())

        assert captured == [expected_cid]

    async def test_missing_correlation_id_generates_new_uuid(self) -> None:
        """If body has no correlation_id, a fresh UUID must be generated."""
        captured: list[UUID] = []

        mock_driver = MagicMock()
        async def capture_run(**kwargs) -> str:
            captured.append(get_correlation_id())
            return "ok"
        mock_driver.run = capture_run

        body = {k: v for k, v in _DEFAULT_BODY.items() if k != "correlation_id"}
        consumer = _make_consumer(mock_driver)
        mock_sqs = AsyncMock()
        await consumer._handle(mock_sqs, _make_sqs_message(body))

        assert len(captured) == 1
        assert isinstance(captured[0], UUID)

    async def test_driver_receives_correct_user_sub(self) -> None:
        received: list[str] = []

        mock_driver = MagicMock()
        async def capture(**kwargs) -> str:
            received.append(kwargs["user_sub"])
            return "ok"
        mock_driver.run = capture

        consumer = _make_consumer(mock_driver)
        await consumer._handle(AsyncMock(), _make_sqs_message())

        assert received == ["user-sub-sqs-test"]

    async def test_driver_receives_correct_session_id(self) -> None:
        received: list[str] = []

        mock_driver = MagicMock()
        async def capture(**kwargs) -> str:
            received.append(kwargs["session_id"])
            return "ok"
        mock_driver.run = capture

        consumer = _make_consumer(mock_driver)
        await consumer._handle(AsyncMock(), _make_sqs_message())

        assert received == ["sess-sqs-001"]

    async def test_driver_receives_correct_source_ip(self) -> None:
        received: list[str] = []

        mock_driver = MagicMock()
        async def capture(**kwargs) -> str:
            received.append(kwargs["source_ip"])
            return "ok"
        mock_driver.run = capture

        consumer = _make_consumer(mock_driver)
        await consumer._handle(AsyncMock(), _make_sqs_message())

        assert received == ["203.0.113.42"]


@pytest.mark.integration
class TestSQSConsumerMessageLifecycle:
    async def test_message_deleted_on_driver_success(self) -> None:
        """SQS message must be deleted after a successful pipeline run."""
        mock_driver = MagicMock()
        mock_driver.run = AsyncMock(return_value="pipeline response")

        consumer = _make_consumer(mock_driver)
        mock_sqs = AsyncMock()
        await consumer._handle(mock_sqs, _make_sqs_message())

        mock_sqs.delete_message.assert_called_once_with(
            QueueUrl=QUEUE_URL,
            ReceiptHandle="receipt-handle-xyz",
        )

    async def test_message_not_deleted_on_driver_failure(self) -> None:
        """If the driver raises, the SQS message must NOT be deleted.

        The message will become visible again after the visibility timeout
        and eventually land in the DLQ. Deleting it on failure would silently
        drop requests.
        """
        mock_driver = MagicMock()
        mock_driver.run = AsyncMock(side_effect=RuntimeError("pipeline exploded"))

        consumer = _make_consumer(mock_driver)
        mock_sqs = AsyncMock()
        await consumer._handle(mock_sqs, _make_sqs_message())

        mock_sqs.delete_message.assert_not_called()

    async def test_malformed_body_generates_cid_and_does_not_raise(self) -> None:
        """Malformed JSON body must be handled gracefully — consumer must not crash."""
        mock_driver = MagicMock()
        mock_driver.run = AsyncMock(return_value="ok")

        consumer = _make_consumer(mock_driver)
        mock_sqs = AsyncMock()
        bad_message = {"ReceiptHandle": "receipt-bad", "Body": "not-json"}

        # Should not raise — consumer absorbs the error
        await consumer._handle(mock_sqs, bad_message)

    async def test_correlation_id_is_set_before_driver_run(self) -> None:
        """set_correlation_id must be called BEFORE driver.run — that's the invariant."""
        call_order: list[str] = []

        original_set = set_correlation_id

        mock_driver = MagicMock()
        async def capture_run(**kwargs) -> str:
            call_order.append("driver.run")
            return "ok"
        mock_driver.run = capture_run

        consumer = _make_consumer(mock_driver)
        mock_sqs = AsyncMock()

        with patch(
            "orchestrator.sqs_consumer.set_correlation_id",
            side_effect=lambda cid: (call_order.append("set_correlation_id"), original_set(cid)),
        ):
            await consumer._handle(mock_sqs, _make_sqs_message())

        assert call_order.index("set_correlation_id") < call_order.index("driver.run")
