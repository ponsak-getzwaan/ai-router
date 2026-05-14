"""Integration tests for AuditLogger against moto-mocked DynamoDB.

Verifies that the audit logger:
  - Actually writes an item to DynamoDB
  - Never includes message text (raw or redacted) in the item
  - Stores entity type names and counts only
  - Drops None values (DynamoDB rejects None attributes)
  - Records the error type as a class name, never a message
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from uuid import uuid4

import boto3
import pytest
from moto import mock_aws

from orchestrator.audit import AuditLogger
from shared.models import (
    BounceResult,
    BouncerLayer,
    ClassifiedIntent,
    ClassifierPath,
    EntityType,
    IntentDomain,
    PipelineEnvelope,
    RoutingContext,
    RoutingPlan,
    StrategistPath,
)

REGION = "ap-southeast-1"
TABLE = "ai-router-audit-test"


def _make_envelope(cid=None) -> PipelineEnvelope:
    return PipelineEnvelope(
        correlation_id=cid or uuid4(),
        user_sub="user-sub-audit-test",
        session_id="sess-audit-001",
        redacted_message="What is VAULT_3A4B5C status?",
        raw_message_hash="a" * 64,
        entity_types_redacted=(EntityType.SG_NRIC,),
        entity_count=1,
        was_redacted=True,
        timestamp=datetime.now(UTC),
        bedrock_region="ap-southeast-1",
        source_ip="10.0.0.1",
    )


def _make_bounce() -> BounceResult:
    return BounceResult(
        allowed=True,
        reason="passed",
        layer=BouncerLayer.RULE_GATE,
        confidence=0.95,
    )


def _make_intent() -> ClassifiedIntent:
    return ClassifiedIntent(
        intent="general_qa",
        domain=IntentDomain.GENERAL_QA,
        confidence=0.92,
        path=ClassifierPath.FAST,
        resolved_message="What is VAULT_3A4B5C status?",
    )


def _make_plan() -> RoutingPlan:
    return RoutingPlan(
        primary_vendor="apac.anthropic.claude-sonnet-4-6-20241022-v2:0",
        context=RoutingContext(
            bedrock_region="ap-southeast-1",
            timeout_seconds=30.0,
            max_retries=2,
            streaming=True,
        ),
        path=StrategistPath.DETERMINISTIC,
    )


@pytest.mark.integration
class TestAuditLoggerDynamoDB:
    async def test_item_written_to_dynamodb(self) -> None:
        with mock_aws():
            boto3.client("dynamodb", region_name=REGION).create_table(
                TableName=TABLE,
                KeySchema=[{"AttributeName": "correlation_id", "KeyType": "HASH"}],
                AttributeDefinitions=[
                    {"AttributeName": "correlation_id", "AttributeType": "S"}
                ],
                BillingMode="PAY_PER_REQUEST",
            )

            cid = uuid4()
            audit = AuditLogger(TABLE, REGION)
            await audit.write(
                envelope=_make_envelope(cid),
                bounce=_make_bounce(),
                intent=_make_intent(),
                plan=_make_plan(),
                vendor_response="Here is your answer.",
                start_time=time.monotonic() - 0.1,
            )

            items = boto3.resource("dynamodb", region_name=REGION).Table(TABLE).scan()["Items"]
        assert len(items) == 1
        assert items[0]["correlation_id"] == str(cid)

    async def test_item_has_no_message_text(self) -> None:
        """Audit item must never contain message content."""
        with mock_aws():
            boto3.client("dynamodb", region_name=REGION).create_table(
                TableName=TABLE,
                KeySchema=[{"AttributeName": "correlation_id", "KeyType": "HASH"}],
                AttributeDefinitions=[
                    {"AttributeName": "correlation_id", "AttributeType": "S"}
                ],
                BillingMode="PAY_PER_REQUEST",
            )

            audit = AuditLogger(TABLE, REGION)
            await audit.write(
                envelope=_make_envelope(),
                bounce=_make_bounce(),
                intent=_make_intent(),
                plan=_make_plan(),
                vendor_response="Some vendor response.",
                start_time=time.monotonic() - 0.1,
            )

            items = boto3.resource("dynamodb", region_name=REGION).Table(TABLE).scan()["Items"]

        item = items[0]
        forbidden = {
            "message", "raw_message", "redacted_message", "content",
            "prompt", "text", "body", "original", "vendor_response",
        }
        present = forbidden & set(item.keys())
        assert not present, f"Forbidden fields in audit item: {present}"

    async def test_item_has_entity_types_not_values(self) -> None:
        """entity_types_redacted contains type names, not PII values."""
        with mock_aws():
            boto3.client("dynamodb", region_name=REGION).create_table(
                TableName=TABLE,
                KeySchema=[{"AttributeName": "correlation_id", "KeyType": "HASH"}],
                AttributeDefinitions=[
                    {"AttributeName": "correlation_id", "AttributeType": "S"}
                ],
                BillingMode="PAY_PER_REQUEST",
            )

            audit = AuditLogger(TABLE, REGION)
            await audit.write(
                envelope=_make_envelope(),
                bounce=_make_bounce(),
                intent=_make_intent(),
                plan=_make_plan(),
                vendor_response="OK",
                start_time=time.monotonic() - 0.1,
            )

            items = boto3.resource("dynamodb", region_name=REGION).Table(TABLE).scan()["Items"]

        entity_types = items[0]["entity_types_redacted"]
        assert isinstance(entity_types, list)
        for et in entity_types:
            assert "@" not in et
            assert " " not in et
            assert et == et.upper()  # type names are uppercase

    async def test_none_values_not_in_item(self) -> None:
        """DynamoDB rejects None — all None fields must be stripped before put_item."""
        with mock_aws():
            boto3.client("dynamodb", region_name=REGION).create_table(
                TableName=TABLE,
                KeySchema=[{"AttributeName": "correlation_id", "KeyType": "HASH"}],
                AttributeDefinitions=[
                    {"AttributeName": "correlation_id", "AttributeType": "S"}
                ],
                BillingMode="PAY_PER_REQUEST",
            )

            audit = AuditLogger(TABLE, REGION)
            # Pass None for bounce/intent/plan to exercise the None-stripping path
            await audit.write(
                envelope=_make_envelope(),
                bounce=None,
                intent=None,
                plan=None,
                vendor_response=None,
                start_time=time.monotonic() - 0.1,
                error_type="BedrockTimeout",
            )

            items = boto3.resource("dynamodb", region_name=REGION).Table(TABLE).scan()["Items"]

        # No None values should be present in the stored item
        for value in items[0].values():
            assert value is not None

    async def test_error_type_is_class_name_only(self) -> None:
        """error_type in DynamoDB item must be the class name, never the full message."""
        with mock_aws():
            boto3.client("dynamodb", region_name=REGION).create_table(
                TableName=TABLE,
                KeySchema=[{"AttributeName": "correlation_id", "KeyType": "HASH"}],
                AttributeDefinitions=[
                    {"AttributeName": "correlation_id", "AttributeType": "S"}
                ],
                BillingMode="PAY_PER_REQUEST",
            )

            audit = AuditLogger(TABLE, REGION)
            await audit.write(
                envelope=_make_envelope(),
                bounce=None,
                intent=None,
                plan=None,
                vendor_response=None,
                start_time=time.monotonic() - 0.1,
                error_type="BedrockTimeout",
            )

            items = boto3.resource("dynamodb", region_name=REGION).Table(TABLE).scan()["Items"]

        assert items[0]["error_type"] == "BedrockTimeout"

    async def test_latency_recorded_as_string(self) -> None:
        """total_latency_ms stored as string (matches AuditRecord schema)."""
        with mock_aws():
            boto3.client("dynamodb", region_name=REGION).create_table(
                TableName=TABLE,
                KeySchema=[{"AttributeName": "correlation_id", "KeyType": "HASH"}],
                AttributeDefinitions=[
                    {"AttributeName": "correlation_id", "AttributeType": "S"}
                ],
                BillingMode="PAY_PER_REQUEST",
            )

            start = time.monotonic() - 0.3  # ~300ms ago
            audit = AuditLogger(TABLE, REGION)
            await audit.write(
                envelope=_make_envelope(),
                bounce=_make_bounce(),
                intent=_make_intent(),
                plan=_make_plan(),
                vendor_response="OK",
                start_time=start,
            )

            items = boto3.resource("dynamodb", region_name=REGION).Table(TABLE).scan()["Items"]

        latency = items[0]["total_latency_ms"]
        assert isinstance(latency, str)
        assert float(latency) > 0
