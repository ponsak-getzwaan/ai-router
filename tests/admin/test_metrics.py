"""Tests for GET /admin/metrics/* endpoints.

Covers: response shape, period_minutes validation, graceful handling of empty
CloudWatch data (zeros/None rather than crashes).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from admin.models import BouncerMetrics, LatencyPercentiles, PipelineMetrics, StrategistMetrics
from tests.admin.conftest import AdminCtx


class TestPipelineMetrics:
    async def test_returns_200(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.get("/admin/api/metrics/pipeline")
        assert resp.status_code == 200

    async def test_response_matches_model(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.get("/admin/api/metrics/pipeline")
        data = resp.json()
        assert "total_requests" in data
        assert "error_rate_pct" in data
        assert "latency_ms" in data
        assert "p50" in data["latency_ms"]

    async def test_period_minutes_defaults_to_60(self, ctx: AdminCtx) -> None:
        await ctx.client.get("/admin/api/metrics/pipeline")
        ctx.cloudwatch.pipeline_metrics.assert_called_once_with(60)

    async def test_custom_period_is_forwarded(self, ctx: AdminCtx) -> None:
        await ctx.client.get("/admin/api/metrics/pipeline?period_minutes=30")
        ctx.cloudwatch.pipeline_metrics.assert_called_once_with(30)

    async def test_period_below_minimum_returns_422(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.get("/admin/api/metrics/pipeline?period_minutes=1")
        assert resp.status_code == 422

    async def test_period_above_maximum_returns_422(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.get("/admin/api/metrics/pipeline?period_minutes=9999")
        assert resp.status_code == 422

    async def test_none_rates_when_no_traffic(self, ctx: AdminCtx) -> None:
        ctx.cloudwatch.pipeline_metrics = AsyncMock(return_value=PipelineMetrics(
            period_minutes=60,
            total_requests=0.0,
            error_rate_pct=None,
            escalation_rate_pct=None,
            latency_ms=LatencyPercentiles(p50=None, p99=None, p999=None),
        ))
        resp = await ctx.client.get("/admin/api/metrics/pipeline")
        assert resp.status_code == 200
        data = resp.json()
        assert data["error_rate_pct"] is None
        assert data["latency_ms"]["p50"] is None


class TestBouncerMetrics:
    async def test_returns_200(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.get("/admin/api/metrics/bouncer")
        assert resp.status_code == 200

    async def test_pass_rate_is_percentage(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.get("/admin/api/metrics/bouncer")
        data = resp.json()
        rate = data.get("pass_rate_pct")
        assert rate is None or 0 <= rate <= 100

    async def test_period_forwarded(self, ctx: AdminCtx) -> None:
        await ctx.client.get("/admin/api/metrics/bouncer?period_minutes=120")
        ctx.cloudwatch.bouncer_metrics.assert_called_once_with(120)

    async def test_zero_total_yields_null_pass_rate(self, ctx: AdminCtx) -> None:
        ctx.cloudwatch.bouncer_metrics = AsyncMock(return_value=BouncerMetrics(
            period_minutes=60,
            total=0.0, passed=0.0, rejected=0.0, escalated=0.0,
            timed_out=0.0, errors=0.0,
            pass_rate_pct=None, avg_confidence=None,
        ))
        resp = await ctx.client.get("/admin/api/metrics/bouncer")
        assert resp.json()["pass_rate_pct"] is None


class TestClassifierMetrics:
    async def test_returns_200(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.get("/admin/api/metrics/classifier")
        assert resp.status_code == 200

    async def test_intent_counts_is_dict(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.get("/admin/api/metrics/classifier")
        assert isinstance(resp.json()["intent_counts"], dict)

    async def test_period_forwarded(self, ctx: AdminCtx) -> None:
        await ctx.client.get("/admin/api/metrics/classifier?period_minutes=15")
        ctx.cloudwatch.classifier_metrics.assert_called_once_with(15)


class TestStrategistMetrics:
    async def test_returns_200(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.get("/admin/api/metrics/strategist")
        assert resp.status_code == 200

    async def test_response_shape(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.get("/admin/api/metrics/strategist")
        data = resp.json()
        assert "total" in data
        assert "vendor_counts" in data
        assert isinstance(data["vendor_counts"], dict)
        assert "policy_blocked" in data
        assert "fallback_used" in data
        assert "deterministic_route" in data
        assert "arbitration_route" in data

    async def test_period_forwarded(self, ctx: AdminCtx) -> None:
        await ctx.client.get("/admin/api/metrics/strategist?period_minutes=120")
        ctx.cloudwatch.strategist_metrics.assert_called_once_with(120)

    async def test_period_below_minimum_returns_422(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.get("/admin/api/metrics/strategist?period_minutes=1")
        assert resp.status_code == 422

    async def test_period_above_maximum_returns_422(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.get("/admin/api/metrics/strategist?period_minutes=9999")
        assert resp.status_code == 422

    async def test_zero_total_returns_empty_vendor_counts(self, ctx: AdminCtx) -> None:
        from unittest.mock import AsyncMock
        ctx.cloudwatch.strategist_metrics = AsyncMock(return_value=StrategistMetrics(
            period_minutes=60,
            total=0.0,
            vendor_counts={},
            policy_blocked=0.0,
            fallback_used=0.0,
            deterministic_route=0.0,
            arbitration_route=0.0,
            errors=0.0,
        ))
        resp = await ctx.client.get("/admin/api/metrics/strategist")
        assert resp.status_code == 200
        assert resp.json()["vendor_counts"] == {}

    async def test_vendor_counts_keys_are_short_names(self, ctx: AdminCtx) -> None:
        data = (await ctx.client.get("/admin/api/metrics/strategist")).json()
        for key in data["vendor_counts"]:
            assert key in ("haiku", "sonnet", "opus"), f"Unexpected vendor key: {key}"


class TestRedactionMetrics:
    async def test_returns_200(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.get("/admin/api/metrics/redaction")
        assert resp.status_code == 200

    async def test_entity_type_counts_never_includes_values(self, ctx: AdminCtx) -> None:
        """Keys must be entity TYPE names (e.g. SG_NRIC), not PII values."""
        resp = await ctx.client.get("/admin/api/metrics/redaction")
        counts = resp.json()["entity_type_counts"]
        for key in counts:
            # Type names are uppercase and contain no spaces or personal info
            assert key.isupper() or "_" in key
            assert "@" not in key
            assert " " not in key

    async def test_period_forwarded(self, ctx: AdminCtx) -> None:
        await ctx.client.get("/admin/api/metrics/redaction?period_minutes=360")
        ctx.cloudwatch.redaction_metrics.assert_called_once_with(360)
