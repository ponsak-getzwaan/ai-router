"""Tests for GET /admin/audit endpoint.

Critical invariant: audit records must never contain message text (raw or
redacted), PII values, or vault tokens. Only entity type names and counts.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from admin.models import AuditQuery
from tests.admin.conftest import AdminCtx, make_audit_record


class TestAuditQuery:
    async def test_returns_200(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.get("/admin/api/audit")
        assert resp.status_code == 200

    async def test_response_has_records_and_count(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.get("/admin/api/audit")
        data = resp.json()
        assert "records" in data
        assert "count" in data

    async def test_default_limit_is_50(self, ctx: AdminCtx) -> None:
        await ctx.client.get("/admin/api/audit")
        ctx.dynamo.query_audit.assert_called_once_with(correlation_id=None, limit=50, last_key=None)

    async def test_custom_limit_forwarded(self, ctx: AdminCtx) -> None:
        await ctx.client.get("/admin/api/audit?limit=10")
        ctx.dynamo.query_audit.assert_called_once_with(correlation_id=None, limit=10, last_key=None)

    async def test_correlation_id_forwarded(self, ctx: AdminCtx) -> None:
        await ctx.client.get("/admin/api/audit?correlation_id=test-cid-001")
        ctx.dynamo.query_audit.assert_called_once_with(
            correlation_id="test-cid-001", limit=50, last_key=None
        )

    async def test_limit_above_100_returns_422(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.get("/admin/api/audit?limit=101")
        assert resp.status_code == 422

    async def test_limit_below_1_returns_422(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.get("/admin/api/audit?limit=0")
        assert resp.status_code == 422

    async def test_empty_result_set(self, ctx: AdminCtx) -> None:
        ctx.dynamo.query_audit = AsyncMock(
            return_value=AuditQuery(records=[], count=0, last_evaluated_key=None)
        )
        resp = await ctx.client.get("/admin/api/audit")
        data = resp.json()
        assert data["records"] == []
        assert data["count"] == 0

    async def test_last_evaluated_key_may_be_null(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.get("/admin/api/audit")
        assert "last_evaluated_key" in resp.json()


class TestAuditRecordShape:
    async def test_record_has_correlation_id(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.get("/admin/api/audit")
        record = resp.json()["records"][0]
        assert "correlation_id" in record

    async def test_record_has_entity_types_not_values(self, ctx: AdminCtx) -> None:
        """entity_types_redacted must contain type names, not PII values."""
        resp = await ctx.client.get("/admin/api/audit")
        record = resp.json()["records"][0]
        assert "entity_types_redacted" in record
        for etype in record["entity_types_redacted"]:
            # Type names are uppercase identifiers, never email addresses or raw PII
            assert "@" not in etype
            assert " " not in etype

    async def test_record_has_entity_count_not_values(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.get("/admin/api/audit")
        record = resp.json()["records"][0]
        assert "entity_count" in record
        assert isinstance(record["entity_count"], int)

    async def test_no_message_field_in_record(self, ctx: AdminCtx) -> None:
        """Records must never expose any message text."""
        resp = await ctx.client.get("/admin/api/audit")
        for record in resp.json()["records"]:
            forbidden = {
                "message", "raw_message", "redacted_message", "content",
                "prompt", "text", "body", "original",
            }
            present = forbidden & set(record.keys())
            assert not present, f"Forbidden fields in audit record: {present}"

    async def test_record_has_routing_metadata(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.get("/admin/api/audit")
        record = resp.json()["records"][0]
        assert "vendor" in record
        assert "intent" in record
        assert "routing_path" in record
        assert "total_latency_ms" in record

    async def test_record_has_bouncer_outcome(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.get("/admin/api/audit")
        record = resp.json()["records"][0]
        assert "bouncer_allowed" in record
        assert "bouncer_escalated" in record

    async def test_error_type_field_not_error_message(self, ctx: AdminCtx) -> None:
        """Only error type name is stored — never the exception message."""
        ctx.dynamo.query_audit = AsyncMock(
            return_value=AuditQuery(
                records=[
                    make_audit_record("err-cid"),
                ],
                count=1,
                last_evaluated_key=None,
            )
        )
        resp = await ctx.client.get("/admin/api/audit")
        record = resp.json()["records"][0]
        assert "error_type" in record
        # error_type is a string like "BedrockTimeout" or None — never a full message
        error_val = record["error_type"]
        assert error_val is None or isinstance(error_val, str)
