"""Tests for POST /admin/test-console.

The test console traces a pre-redacted message through bouncer → classifier →
strategist. It is always dry_run in Phase 1; the vendor adapter is never invoked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.admin.conftest import AdminCtx


def _make_bounce_result(
    *,
    allowed: bool = True,
    reason: str = "passed",
    escalate: bool = False,
    timed_out: bool = False,
) -> MagicMock:
    result = MagicMock()
    result.allowed = allowed
    result.reason = reason
    result.layer = "rule_gate"
    result.confidence = 0.95
    result.escalate = escalate
    result.timed_out = timed_out
    return result


def _make_intent_result(
    *,
    intent: str = "general_qa",
    escalate: bool = False,
) -> MagicMock:
    result = MagicMock()
    result.intent = intent
    result.domain = "general"
    result.confidence = 0.92
    result.path = "fast_path"
    result.escalate = escalate
    return result


def _make_routing_plan() -> MagicMock:
    plan = MagicMock()
    plan.primary_vendor = "apac.anthropic.claude-sonnet-4-6-20241022-v2:0"
    plan.path = "deterministic"
    plan.blocked = False
    plan.policy_modified = False
    plan.applied_policies = []
    return plan


def _patch_pipeline(bounce_result=None, intent_result=None, routing_plan=None):
    """Context manager that patches all three pipeline layers."""
    bounce_result = bounce_result or _make_bounce_result()
    intent_result = intent_result or _make_intent_result()
    routing_plan = routing_plan or _make_routing_plan()

    mock_bouncer = MagicMock()
    mock_bouncer.bounce = AsyncMock(return_value=bounce_result)

    mock_classifier = MagicMock()
    mock_classifier.classify = AsyncMock(return_value=intent_result)

    mock_strategist = MagicMock()
    mock_strategist.route = AsyncMock(return_value=routing_plan)

    mock_redis = AsyncMock()

    return (
        patch("admin.routers.test_console.Bouncer", return_value=mock_bouncer),
        patch("admin.routers.test_console.Classifier", return_value=mock_classifier),
        patch("admin.routers.test_console.Strategist", return_value=mock_strategist),
        patch("admin.routers.test_console.BedrockRuntime"),
        patch("admin.routers.test_console.aioredis.from_url", return_value=mock_redis),
    )


class TestTestConsoleResponseShape:
    async def test_returns_200(self, ctx: AdminCtx) -> None:
        patches = _patch_pipeline()
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            resp = await ctx.client.post(
                "/admin/test-console",
                json={"redacted_message": "What is VAULT_3A4B?"},
            )
        assert resp.status_code == 200

    async def test_response_has_required_fields(self, ctx: AdminCtx) -> None:
        patches = _patch_pipeline()
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            resp = await ctx.client.post(
                "/admin/test-console",
                json={"redacted_message": "What is VAULT_3A4B?"},
            )
        data = resp.json()
        assert "correlation_id" in data
        assert "dry_run" in data
        assert "layers" in data
        assert "total_latency_ms" in data

    async def test_dry_run_defaults_to_true(self, ctx: AdminCtx) -> None:
        patches = _patch_pipeline()
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            resp = await ctx.client.post(
                "/admin/test-console",
                json={"redacted_message": "What is VAULT_3A4B?"},
            )
        assert resp.json()["dry_run"] is True

    async def test_layers_list_is_present(self, ctx: AdminCtx) -> None:
        patches = _patch_pipeline()
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            resp = await ctx.client.post(
                "/admin/test-console",
                json={"redacted_message": "What is VAULT_3A4B?"},
            )
        assert isinstance(resp.json()["layers"], list)

    async def test_each_layer_has_name_latency_outcome(self, ctx: AdminCtx) -> None:
        patches = _patch_pipeline()
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            resp = await ctx.client.post(
                "/admin/test-console",
                json={"redacted_message": "What is VAULT_3A4B?"},
            )
        for layer in resp.json()["layers"]:
            assert "layer" in layer
            assert "latency_ms" in layer
            assert "outcome" in layer


class TestTestConsolePipelineFlow:
    async def test_bouncer_allowed_proceeds_to_classifier(self, ctx: AdminCtx) -> None:
        patches = _patch_pipeline(
            bounce_result=_make_bounce_result(allowed=True),
            intent_result=_make_intent_result(),
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            resp = await ctx.client.post(
                "/admin/test-console",
                json={"redacted_message": "What is VAULT_3A4B?"},
            )
        layer_names = [l["layer"] for l in resp.json()["layers"]]
        assert "bouncer" in layer_names
        assert "classifier" in layer_names

    async def test_bouncer_rejection_stops_pipeline(self, ctx: AdminCtx) -> None:
        """When bouncer rejects, classifier and strategist must not run."""
        patches = _patch_pipeline(
            bounce_result=_make_bounce_result(allowed=False, reason="banned_user"),
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            resp = await ctx.client.post(
                "/admin/test-console",
                json={"redacted_message": "What is VAULT_3A4B?"},
            )
        layer_names = [l["layer"] for l in resp.json()["layers"]]
        assert "bouncer" in layer_names
        assert "classifier" not in layer_names
        assert "strategist" not in layer_names

    async def test_classifier_runs_after_bouncer_passes(self, ctx: AdminCtx) -> None:
        patches = _patch_pipeline()
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            resp = await ctx.client.post(
                "/admin/test-console",
                json={"redacted_message": "What is VAULT_3A4B?"},
            )
        layer_names = [l["layer"] for l in resp.json()["layers"]]
        assert "classifier" in layer_names

    async def test_strategist_skipped_when_classifier_escalates(self, ctx: AdminCtx) -> None:
        patches = _patch_pipeline(intent_result=_make_intent_result(escalate=True))
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            resp = await ctx.client.post(
                "/admin/test-console",
                json={"redacted_message": "What is VAULT_3A4B?"},
            )
        layer_names = [l["layer"] for l in resp.json()["layers"]]
        assert "strategist" not in layer_names

    async def test_dry_run_false_adds_skipped_adapter_layer(self, ctx: AdminCtx) -> None:
        """dry_run=False still skips vendor invocation but records the adapter layer."""
        patches = _patch_pipeline()
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            resp = await ctx.client.post(
                "/admin/test-console",
                json={"redacted_message": "What is VAULT_3A4B?", "dry_run": False},
            )
        layer_names = [l["layer"] for l in resp.json()["layers"]]
        assert "adapter" in layer_names
        adapter = next(l for l in resp.json()["layers"] if l["layer"] == "adapter")
        assert "skipped" in adapter["outcome"]

    async def test_bouncer_error_continues_with_error_type(self, ctx: AdminCtx) -> None:
        mock_bouncer = MagicMock()
        mock_bouncer.bounce = AsyncMock(side_effect=RuntimeError("connection refused"))
        mock_redis = AsyncMock()

        with (
            patch("admin.routers.test_console.Bouncer", return_value=mock_bouncer),
            patch("admin.routers.test_console.Classifier"),
            patch("admin.routers.test_console.Strategist"),
            patch("admin.routers.test_console.BedrockRuntime"),
            patch("admin.routers.test_console.aioredis.from_url", return_value=mock_redis),
        ):
            resp = await ctx.client.post(
                "/admin/test-console",
                json={"redacted_message": "What is VAULT_3A4B?"},
            )
        assert resp.status_code == 200
        bouncer_layer = next(
            (l for l in resp.json()["layers"] if l["layer"] == "bouncer"), None
        )
        assert bouncer_layer is not None
        assert "error_type" in bouncer_layer["outcome"]
        assert bouncer_layer["outcome"]["error_type"] == "RuntimeError"


class TestTestConsoleValidation:
    async def test_empty_redacted_message_returns_422(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.post(
            "/admin/test-console",
            json={"redacted_message": ""},
        )
        assert resp.status_code == 422

    async def test_missing_redacted_message_returns_422(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.post("/admin/test-console", json={})
        assert resp.status_code == 422

    async def test_message_over_4096_chars_returns_422(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.post(
            "/admin/test-console",
            json={"redacted_message": "x" * 4097},
        )
        assert resp.status_code == 422

    async def test_message_exactly_4096_chars_accepted(self, ctx: AdminCtx) -> None:
        patches = _patch_pipeline()
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            resp = await ctx.client.post(
                "/admin/test-console",
                json={"redacted_message": "x" * 4096},
            )
        assert resp.status_code == 200
