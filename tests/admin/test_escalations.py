"""Tests for GET/POST /admin/escalations/*.

Critical invariant: escalation previews must show only the redacted_message
field from the SQS body — never the original PII values, never de-tokenised text.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from admin.models import EscalationList
from tests.admin.conftest import AdminCtx, make_escalation_message


class TestListEscalations:
    async def test_returns_200(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.get("/admin/escalations")
        assert resp.status_code == 200

    async def test_empty_queue_returns_empty_list(self, ctx: AdminCtx) -> None:
        ctx.sqs.list_pending = AsyncMock(
            return_value=EscalationList(messages=[], queue_depth=0)
        )
        resp = await ctx.client.get("/admin/escalations")
        data = resp.json()
        assert data["messages"] == []
        assert data["queue_depth"] == 0

    async def test_messages_contain_required_fields(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.get("/admin/escalations")
        msg = resp.json()["messages"][0]
        assert "correlation_id" in msg
        assert "redacted_preview" in msg
        assert "receipt_handle" in msg
        assert "entity_types" in msg

    async def test_preview_is_redacted_not_raw(self, ctx: AdminCtx) -> None:
        """The preview field must come from redacted_message in SQS body."""
        ctx.sqs.list_pending = AsyncMock(
            return_value=EscalationList(
                messages=[make_escalation_message()],
                queue_depth=1,
            )
        )
        resp = await ctx.client.get("/admin/escalations")
        preview = resp.json()["messages"][0]["redacted_preview"]
        # The fixture uses "VAULT_" as the redacted token placeholder
        assert "VAULT_" in preview, "Preview should contain redacted vault tokens, not raw PII"

    async def test_no_raw_message_field_in_response(self, ctx: AdminCtx) -> None:
        """raw_message must never appear in the API response."""
        resp = await ctx.client.get("/admin/escalations")
        for msg in resp.json()["messages"]:
            assert "raw_message" not in msg
            assert "original" not in msg

    async def test_max_messages_respected(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.get("/admin/escalations?max_messages=5")
        assert resp.status_code == 200
        ctx.sqs.list_pending.assert_called_once_with(5)

    async def test_max_messages_above_10_returns_422(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.get("/admin/escalations?max_messages=11")
        assert resp.status_code == 422


class TestApproveEscalation:
    async def test_approve_returns_200(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.post(
            "/admin/escalations/esc-cid-001/approve",
            json={"receipt_handle": "receipt-handle-abc"},
        )
        assert resp.status_code == 200

    async def test_approve_action_field_is_approved(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.post(
            "/admin/escalations/esc-cid-001/approve",
            json={"receipt_handle": "receipt-handle-abc"},
        )
        assert resp.json()["action"] == "approved"

    async def test_approve_calls_sqs_service_with_receipt_handle(self, ctx: AdminCtx) -> None:
        await ctx.client.post(
            "/admin/escalations/esc-cid-001/approve",
            json={"receipt_handle": "my-receipt-handle"},
        )
        ctx.sqs.approve.assert_called_once_with("my-receipt-handle", "esc-cid-001")

    async def test_approve_correlation_id_in_response(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.post(
            "/admin/escalations/esc-cid-001/approve",
            json={"receipt_handle": "receipt-handle-abc"},
        )
        assert resp.json()["correlation_id"] == "esc-cid-001"

    async def test_approve_missing_receipt_handle_returns_422(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.post("/admin/escalations/esc-cid-001/approve", json={})
        assert resp.status_code == 422


class TestRejectEscalation:
    async def test_reject_returns_200(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.post(
            "/admin/escalations/esc-cid-001/reject",
            json={"receipt_handle": "receipt-handle-abc"},
        )
        assert resp.status_code == 200

    async def test_reject_action_field_is_rejected(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.post(
            "/admin/escalations/esc-cid-001/reject",
            json={"receipt_handle": "receipt-handle-abc"},
        )
        assert resp.json()["action"] == "rejected"

    async def test_reject_calls_sqs_service(self, ctx: AdminCtx) -> None:
        await ctx.client.post(
            "/admin/escalations/esc-cid-001/reject",
            json={"receipt_handle": "my-handle"},
        )
        ctx.sqs.reject.assert_called_once_with("my-handle", "esc-cid-001")


class TestRequeueEscalation:
    async def test_requeue_returns_200(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.post(
            "/admin/escalations/esc-cid-001/requeue",
            json={
                "receipt_handle": "receipt-handle-abc",
                "annotation": "Needs senior review",
            },
        )
        assert resp.status_code == 200

    async def test_requeue_action_field_is_requeued(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.post(
            "/admin/escalations/esc-cid-001/requeue",
            json={
                "receipt_handle": "receipt-handle-abc",
                "annotation": "Needs senior review",
            },
        )
        assert resp.json()["action"] == "requeued"

    async def test_requeue_passes_annotation_to_service(self, ctx: AdminCtx) -> None:
        await ctx.client.post(
            "/admin/escalations/esc-cid-001/requeue",
            json={
                "receipt_handle": "my-handle",
                "annotation": "Flag for compliance team",
            },
        )
        ctx.sqs.requeue.assert_called_once_with(
            "my-handle", "esc-cid-001", "Flag for compliance team"
        )

    async def test_requeue_empty_annotation_returns_422(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.post(
            "/admin/escalations/esc-cid-001/requeue",
            json={"receipt_handle": "my-handle", "annotation": ""},
        )
        assert resp.status_code == 422

    async def test_requeue_missing_annotation_returns_422(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.post(
            "/admin/escalations/esc-cid-001/requeue",
            json={"receipt_handle": "my-handle"},
        )
        assert resp.status_code == 422
