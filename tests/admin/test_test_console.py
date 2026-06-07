"""Tests for POST /admin/test-console.

The test console submits the raw message to the incoming SQS queue and polls
the DynamoDB audit table for the result. Tests mock _send_to_sqs and
dynamo.query_audit — no pipeline layers are instantiated directly.
"""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest

from admin.config import AdminConfig
from admin.main import app as admin_app
from admin.models import AuditQuery, AuditRecord
from tests.admin.conftest import AdminCtx, make_audit_record

_SQS_TEST_URL = "https://sqs.ap-southeast-1.amazonaws.com/012345678901/ai-router-incoming"


def _make_audit_record(**kwargs: object) -> AuditRecord:
    base = make_audit_record()
    return base.model_copy(update=kwargs)


def _patch_sqs() -> "AbstractContextManager[AsyncMock]":
    return patch("admin.routers.test_console._send_to_sqs", new_callable=AsyncMock)


def _set_sqs_url(url: str = _SQS_TEST_URL) -> None:
    """Configure a non-empty sqs_incoming_url on app.state.config."""
    admin_app.state.config = AdminConfig(sqs_incoming_url=url)


class TestTestConsoleResponseShape:
    async def test_returns_200(self, ctx: AdminCtx) -> None:
        _set_sqs_url()
        with _patch_sqs():
            resp = await ctx.client.post(
                "/admin/test-console",
                json={"message": "What is VAULT_3A4B?"},
            )
        assert resp.status_code == 200

    async def test_response_has_required_fields(self, ctx: AdminCtx) -> None:
        _set_sqs_url()
        with _patch_sqs():
            resp = await ctx.client.post(
                "/admin/test-console",
                json={"message": "What is VAULT_3A4B?"},
            )
        data = resp.json()
        assert "correlation_id" in data
        assert "layers" in data
        assert "total_latency_ms" in data
        assert "timed_out" in data
        assert "final_vendor" in data

    async def test_no_dry_run_field_in_response(self, ctx: AdminCtx) -> None:
        _set_sqs_url()
        with _patch_sqs():
            resp = await ctx.client.post(
                "/admin/test-console",
                json={"message": "What is VAULT_3A4B?"},
            )
        assert "dry_run" not in resp.json()

    async def test_layers_list_is_present(self, ctx: AdminCtx) -> None:
        _set_sqs_url()
        with _patch_sqs():
            resp = await ctx.client.post(
                "/admin/test-console",
                json={"message": "What is VAULT_3A4B?"},
            )
        assert isinstance(resp.json()["layers"], list)

    async def test_each_layer_has_name_latency_outcome(self, ctx: AdminCtx) -> None:
        _set_sqs_url()
        with _patch_sqs():
            resp = await ctx.client.post(
                "/admin/test-console",
                json={"message": "What is VAULT_3A4B?"},
            )
        for layer in resp.json()["layers"]:
            assert "layer" in layer
            assert "latency_ms" in layer
            assert "outcome" in layer


class TestTestConsolePipelineTrace:
    async def test_redactor_layer_always_present(self, ctx: AdminCtx) -> None:
        _set_sqs_url()
        with _patch_sqs():
            resp = await ctx.client.post(
                "/admin/test-console",
                json={"message": "What is VAULT_3A4B?"},
            )
        layer_names = [lyr["layer"] for lyr in resp.json()["layers"]]
        assert "redactor" in layer_names

    async def test_redactor_reports_was_redacted_true(self, ctx: AdminCtx) -> None:
        _set_sqs_url()
        ctx.dynamo.query_audit = AsyncMock(
            return_value=AuditQuery(
                records=[_make_audit_record(was_redacted=True, entity_count=1)],
                count=1,
                last_evaluated_key=None,
            )
        )
        with _patch_sqs():
            resp = await ctx.client.post(
                "/admin/test-console",
                json={"message": "My IC is S1234567A"},
            )
        redactor = next(lyr for lyr in resp.json()["layers"] if lyr["layer"] == "redactor")
        assert redactor["outcome"]["was_redacted"] is True
        assert redactor["outcome"]["entity_count"] == 1

    async def test_bouncer_layer_present_when_record_has_bouncer_allowed(self, ctx: AdminCtx) -> None:
        _set_sqs_url()
        with _patch_sqs():
            resp = await ctx.client.post(
                "/admin/test-console",
                json={"message": "What is VAULT_3A4B?"},
            )
        layer_names = [lyr["layer"] for lyr in resp.json()["layers"]]
        assert "bouncer" in layer_names

    async def test_classifier_layer_present_when_intent_set(self, ctx: AdminCtx) -> None:
        _set_sqs_url()
        with _patch_sqs():
            resp = await ctx.client.post(
                "/admin/test-console",
                json={"message": "What is VAULT_3A4B?"},
            )
        layer_names = [lyr["layer"] for lyr in resp.json()["layers"]]
        assert "classifier" in layer_names

    async def test_strategist_layer_present_when_vendor_set(self, ctx: AdminCtx) -> None:
        _set_sqs_url()
        with _patch_sqs():
            resp = await ctx.client.post(
                "/admin/test-console",
                json={"message": "What is VAULT_3A4B?"},
            )
        layer_names = [lyr["layer"] for lyr in resp.json()["layers"]]
        assert "strategist" in layer_names

    async def test_adapter_layer_present_when_vendor_not_blocked(self, ctx: AdminCtx) -> None:
        _set_sqs_url()
        with _patch_sqs():
            resp = await ctx.client.post(
                "/admin/test-console",
                json={"message": "What is VAULT_3A4B?"},
            )
        layer_names = [lyr["layer"] for lyr in resp.json()["layers"]]
        assert "adapter" in layer_names

    async def test_bouncer_blocked_stops_pipeline(self, ctx: AdminCtx) -> None:
        _set_sqs_url()
        ctx.dynamo.query_audit = AsyncMock(
            return_value=AuditQuery(
                records=[_make_audit_record(
                    bouncer_allowed=False,
                    bouncer_escalated=False,
                    intent=None,
                    vendor=None,
                    routing_path=None,
                    policy_blocked=None,
                )],
                count=1,
                last_evaluated_key=None,
            )
        )
        with _patch_sqs():
            resp = await ctx.client.post(
                "/admin/test-console",
                json={"message": "do something illegal"},
            )
        layer_names = [lyr["layer"] for lyr in resp.json()["layers"]]
        assert "bouncer" in layer_names
        assert "classifier" not in layer_names
        assert "strategist" not in layer_names

    async def test_classifier_escalated_stops_pipeline(self, ctx: AdminCtx) -> None:
        _set_sqs_url()
        ctx.dynamo.query_audit = AsyncMock(
            return_value=AuditQuery(
                records=[_make_audit_record(
                    intent="general_qa",
                    intent_escalated=True,
                    vendor=None,
                    routing_path=None,
                    policy_blocked=None,
                )],
                count=1,
                last_evaluated_key=None,
            )
        )
        with _patch_sqs():
            resp = await ctx.client.post(
                "/admin/test-console",
                json={"message": "unclear question"},
            )
        layer_names = [lyr["layer"] for lyr in resp.json()["layers"]]
        assert "classifier" in layer_names
        assert "strategist" not in layer_names

    async def test_policy_blocked_sets_final_vendor_none(self, ctx: AdminCtx) -> None:
        _set_sqs_url()
        ctx.dynamo.query_audit = AsyncMock(
            return_value=AuditQuery(
                records=[_make_audit_record(
                    vendor="apac.anthropic.claude-3-5-sonnet-20241022-v2:0",
                    policy_blocked=True,
                )],
                count=1,
                last_evaluated_key=None,
            )
        )
        with _patch_sqs():
            resp = await ctx.client.post(
                "/admin/test-console",
                json={"message": "route me"},
            )
        assert resp.json()["final_vendor"] is None

    async def test_final_vendor_set_when_not_blocked(self, ctx: AdminCtx) -> None:
        _set_sqs_url()
        with _patch_sqs():
            resp = await ctx.client.post(
                "/admin/test-console",
                json={"message": "What is VAULT_3A4B?"},
            )
        assert resp.json()["final_vendor"] == "apac.anthropic.claude-3-5-sonnet-20241022-v2:0"

    async def test_response_field_passes_through_vendor_response(self, ctx: AdminCtx) -> None:
        _set_sqs_url()
        ctx.dynamo.query_audit = AsyncMock(
            return_value=AuditQuery(
                records=[_make_audit_record(vendor_response_redacted="The answer is 42.")],
                count=1,
                last_evaluated_key=None,
            )
        )
        with _patch_sqs():
            resp = await ctx.client.post(
                "/admin/test-console",
                json={"message": "What is the answer?"},
            )
        assert resp.json()["response"] == "The answer is 42."


class TestTestConsoleTimeout:
    async def test_timeout_returns_timed_out_true(self, ctx: AdminCtx) -> None:
        _set_sqs_url()
        ctx.dynamo.query_audit = AsyncMock(
            return_value=AuditQuery(records=[], count=0, last_evaluated_key=None)
        )
        with (
            _patch_sqs(),
            patch("admin.routers.test_console._POLL_TIMEOUT_S", 0.1),
            patch("admin.routers.test_console._POLL_INTERVAL_S", 0.05),
        ):
            resp = await ctx.client.post(
                "/admin/test-console",
                json={"message": "What is VAULT_3A4B?"},
            )
        data = resp.json()
        assert resp.status_code == 200
        assert data["timed_out"] is True
        assert data["layers"] == []
        assert data["final_vendor"] is None

    async def test_sqs_not_configured_returns_error(self, ctx: AdminCtx) -> None:
        # Leave sqs_incoming_url as "" (default from conftest AdminConfig())
        resp = await ctx.client.post(
            "/admin/test-console",
            json={"message": "test"},
        )
        data = resp.json()
        assert resp.status_code == 200
        assert data["error"] == "SQSNotConfigured"


class TestTestConsoleValidation:
    async def test_empty_message_returns_422(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.post(
            "/admin/test-console",
            json={"message": ""},
        )
        assert resp.status_code == 422

    async def test_missing_message_returns_422(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.post("/admin/test-console", json={})
        assert resp.status_code == 422

    async def test_message_over_4096_chars_returns_422(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.post(
            "/admin/test-console",
            json={"message": "x" * 4097},
        )
        assert resp.status_code == 422

    async def test_message_exactly_4096_chars_accepted(self, ctx: AdminCtx) -> None:
        _set_sqs_url()
        with _patch_sqs():
            resp = await ctx.client.post(
                "/admin/test-console",
                json={"message": "x" * 4096},
            )
        assert resp.status_code == 200

    async def test_old_redacted_message_field_returns_422(self, ctx: AdminCtx) -> None:
        """Ensure the old API shape is rejected (extra='forbid' on the model)."""
        resp = await ctx.client.post(
            "/admin/test-console",
            json={"redacted_message": "hello"},
        )
        assert resp.status_code == 422
