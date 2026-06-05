"""Tests for GET/PUT /admin/routing-rules endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock

from admin.models import RoutingRule
from tests.admin.conftest import AdminCtx, make_routing_rule


class TestListRoutingRules:
    async def test_returns_200(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.get("/admin/routing-rules")
        assert resp.status_code == 200

    async def test_returns_list(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.get("/admin/routing-rules")
        assert isinstance(resp.json(), list)

    async def test_list_contains_required_fields(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.get("/admin/routing-rules")
        rule = resp.json()[0]
        assert "intent" in rule
        assert "vendor" in rule
        assert "fallback" in rule
        assert "description" in rule

    async def test_calls_dynamo_list(self, ctx: AdminCtx) -> None:
        await ctx.client.get("/admin/routing-rules")
        ctx.dynamo.list_routing_rules.assert_called_once()

    async def test_empty_table_returns_empty_list(self, ctx: AdminCtx) -> None:
        ctx.dynamo.list_routing_rules = AsyncMock(return_value=[])
        resp = await ctx.client.get("/admin/routing-rules")
        assert resp.json() == []

    async def test_multiple_rules_returned(self, ctx: AdminCtx) -> None:
        ctx.dynamo.list_routing_rules = AsyncMock(
            return_value=[
                make_routing_rule("general_qa"),
                make_routing_rule("code_assistance"),
            ]
        )
        resp = await ctx.client.get("/admin/routing-rules")
        assert len(resp.json()) == 2


class TestGetRoutingRule:
    async def test_returns_200_when_found(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.get("/admin/routing-rules/general_qa")
        assert resp.status_code == 200

    async def test_response_contains_intent(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.get("/admin/routing-rules/general_qa")
        assert resp.json()["intent"] == "general_qa"

    async def test_calls_dynamo_get_with_intent(self, ctx: AdminCtx) -> None:
        await ctx.client.get("/admin/routing-rules/code_assistance")
        ctx.dynamo.get_routing_rule.assert_called_once_with("code_assistance")

    async def test_missing_intent_returns_404(self, ctx: AdminCtx) -> None:
        ctx.dynamo.get_routing_rule = AsyncMock(return_value=None)
        resp = await ctx.client.get("/admin/routing-rules/nonexistent_intent")
        assert resp.status_code == 404

    async def test_404_detail_mentions_intent(self, ctx: AdminCtx) -> None:
        ctx.dynamo.get_routing_rule = AsyncMock(return_value=None)
        resp = await ctx.client.get("/admin/routing-rules/nonexistent_intent")
        assert "nonexistent_intent" in resp.json()["detail"]


class TestPutRoutingRule:
    async def test_returns_200(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.put(
            "/admin/routing-rules/general_qa",
            json={"vendor": "apac.anthropic.claude-3-5-sonnet-20241022-v2:0"},
        )
        assert resp.status_code == 200

    async def test_calls_dynamo_put_with_intent_and_body(self, ctx: AdminCtx) -> None:
        await ctx.client.put(
            "/admin/routing-rules/general_qa",
            json={"vendor": "apac.anthropic.claude-3-haiku-20240307-v1:0"},
        )
        ctx.dynamo.put_routing_rule.assert_called_once()
        call_args = ctx.dynamo.put_routing_rule.call_args
        assert call_args.args[0] == "general_qa"

    async def test_response_is_routing_rule_shape(self, ctx: AdminCtx) -> None:
        ctx.dynamo.put_routing_rule = AsyncMock(
            return_value=RoutingRule(
                intent="general_qa",
                vendor="apac.anthropic.claude-3-haiku-20240307-v1:0",
                fallback=None,
                description=None,
            )
        )
        resp = await ctx.client.put(
            "/admin/routing-rules/general_qa",
            json={"vendor": "apac.anthropic.claude-3-haiku-20240307-v1:0"},
        )
        data = resp.json()
        assert data["intent"] == "general_qa"
        assert data["vendor"] == "apac.anthropic.claude-3-haiku-20240307-v1:0"

    async def test_empty_vendor_returns_422(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.put(
            "/admin/routing-rules/general_qa",
            json={"vendor": ""},
        )
        assert resp.status_code == 422

    async def test_missing_vendor_returns_422(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.put(
            "/admin/routing-rules/general_qa",
            json={"description": "Some description"},
        )
        assert resp.status_code == 422

    async def test_extra_fields_rejected(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.put(
            "/admin/routing-rules/general_qa",
            json={
                "vendor": "apac.anthropic.claude-3-5-sonnet-20241022-v2:0",
                "unknown_field": "bad",
            },
        )
        assert resp.status_code == 422

    async def test_optional_fallback_and_description_accepted(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.put(
            "/admin/routing-rules/general_qa",
            json={
                "vendor": "apac.anthropic.claude-3-5-sonnet-20241022-v2:0",
                "fallback": "apac.anthropic.claude-3-haiku-20240307-v1:0",
                "description": "Handles general questions",
            },
        )
        assert resp.status_code == 200
