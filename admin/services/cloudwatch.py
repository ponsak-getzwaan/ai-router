"""CloudWatch metrics queries for the admin dashboard.

Queries the AIRouter CloudWatch namespace for per-layer operational stats.
All values are aggregated (counts, rates, latencies) — no user data.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import aioboto3  # type: ignore[import-untyped]

from admin.models import (
    BouncerMetrics,
    ClassifierMetrics,
    LatencyPercentiles,
    PipelineMetrics,
    RedactionMetrics,
    StrategistMetrics,
)
from shared.logging import safe_log


def _window(period_minutes: int) -> tuple[datetime, datetime]:
    end = datetime.now(UTC)
    start = end - timedelta(minutes=period_minutes)
    return start, end


def _safe_sum(datapoints: list[dict[str, Any]]) -> float:
    return float(sum(d.get("Sum", d.get("SampleCount", 0.0)) for d in datapoints))


def _safe_avg(datapoints: list[dict[str, Any]]) -> float | None:
    pts = [d["Average"] for d in datapoints if "Average" in d]
    return sum(pts) / len(pts) if pts else None


def _rate_pct(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator * 100, 2)


class CloudWatchService:
    def __init__(self, namespace: str, region: str) -> None:
        self._ns = namespace
        self._region = region
        self._session: aioboto3.Session = aioboto3.Session()

    async def _get_metric_stats(
        self,
        metric_name: str,
        stat: str,
        period_seconds: int,
        start: datetime,
        end: datetime,
        dimensions: list[dict[str, str]] | None = None,
    ) -> list[dict[str, Any]]:
        try:
            async with self._session.client("cloudwatch", region_name=self._region) as cw:
                resp = await cw.get_metric_statistics(
                    Namespace=self._ns,
                    MetricName=metric_name,
                    Dimensions=dimensions or [],
                    StartTime=start,
                    EndTime=end,
                    Period=period_seconds,
                    Statistics=[stat],
                )
                return cast(list[dict[str, Any]], resp.get("Datapoints", []))
        except Exception as exc:
            safe_log.warning(
                "admin.cloudwatch.error",
                error_type=type(exc).__name__,
            )
            return []

    async def pipeline_metrics(self, period_minutes: int = 60) -> PipelineMetrics:
        start, end = _window(period_minutes)
        period_s = period_minutes * 60

        requests_pts = await self._get_metric_stats(
            "RequestCount", "Sum", period_s, start, end,
            [{"Name": "Layer", "Value": "orchestrator"}],
        )
        errors_pts = await self._get_metric_stats(
            "ErrorCount", "Sum", period_s, start, end,
            [{"Name": "Layer", "Value": "orchestrator"}],
        )
        escalations_pts = await self._get_metric_stats(
            "EscalationCount", "Sum", period_s, start, end,
        )
        latency_pts = await self._get_metric_stats(
            "RequestLatencyMs", "Average", period_s, start, end,
            [{"Name": "Layer", "Value": "orchestrator"}],
        )
        p99_pts = await self._get_metric_stats(
            "RequestLatencyMs", "p99", period_s, start, end,
            [{"Name": "Layer", "Value": "orchestrator"}],
        )

        total = _safe_sum(requests_pts)
        errors = _safe_sum(errors_pts)
        escalations = _safe_sum(escalations_pts)

        return PipelineMetrics(
            period_minutes=period_minutes,
            total_requests=total,
            error_rate_pct=_rate_pct(errors, total),
            escalation_rate_pct=_rate_pct(escalations, total),
            latency_ms=LatencyPercentiles(
                p50=_safe_avg(latency_pts),
                p99=_safe_avg(p99_pts),
                p999=None,
            ),
        )

    async def bouncer_metrics(self, period_minutes: int = 60) -> BouncerMetrics:
        start, end = _window(period_minutes)
        period_s = period_minutes * 60

        async def _sum(metric: str, dim_val: str | None = None) -> float:
            dims = [{"Name": "Layer", "Value": "bouncer"}] if dim_val is None else [
                {"Name": "Layer", "Value": "bouncer"},
                {"Name": "Outcome", "Value": dim_val},
            ]
            pts = await self._get_metric_stats(metric, "Sum", period_s, start, end, dims)
            return _safe_sum(pts)

        total = await _sum("RequestCount")
        passed = await _sum("RequestCount", "passed")
        rejected = await _sum("RequestCount", "rejected")
        escalated = await _sum("RequestCount", "escalated")
        timed_out = await _sum("BouncerTimeout")
        errors = await _sum("BouncerError")
        conf_pts = await self._get_metric_stats(
            "BouncerConfidence", "Average", period_s, start, end,
            [{"Name": "Layer", "Value": "bouncer"}],
        )

        return BouncerMetrics(
            period_minutes=period_minutes,
            total=total,
            passed=passed,
            rejected=rejected,
            escalated=escalated,
            timed_out=timed_out,
            errors=errors,
            pass_rate_pct=_rate_pct(passed, total),
            avg_confidence=_safe_avg(conf_pts),
        )

    async def classifier_metrics(self, period_minutes: int = 60) -> ClassifierMetrics:
        start, end = _window(period_minutes)
        period_s = period_minutes * 60

        async def _sum(metric: str, dims: list[dict[str, str]] | None = None) -> float:
            pts = await self._get_metric_stats(metric, "Sum", period_s, start, end, dims)
            return _safe_sum(pts)

        total = await _sum("RequestCount", [{"Name": "Layer", "Value": "classifier"}])
        fast = await _sum("ClassifierPath", [{"Name": "Path", "Value": "fast"}])
        deep = await _sum("ClassifierPath", [{"Name": "Path", "Value": "deep"}])
        escalated = await _sum(
            "RequestCount",
            [{"Name": "Layer", "Value": "classifier"}, {"Name": "Outcome", "Value": "escalated"}],
        )

        # Intent distribution — query top-level intents
        intent_counts: dict[str, float] = {}
        for intent in ("general_qa", "code_assistance", "simple_transactional", "ambiguous"):
            count = await _sum(
                "IntentCount",
                [{"Name": "Intent", "Value": intent}],
            )
            if count > 0:
                intent_counts[intent] = count

        return ClassifierMetrics(
            period_minutes=period_minutes,
            total=total,
            fast_path=fast,
            deep_path=deep,
            escalated=escalated,
            intent_counts=intent_counts,
        )

    async def strategist_metrics(self, period_minutes: int = 60) -> StrategistMetrics:
        start, end = _window(period_minutes)
        period_s = period_minutes * 60

        async def _sum(metric: str, dims: list[dict[str, str]] | None = None) -> float:
            pts = await self._get_metric_stats(metric, "Sum", period_s, start, end, dims)
            return _safe_sum(pts)

        total = await _sum("RequestCount", [{"Name": "Layer", "Value": "strategist"}])
        policy_blocked = await _sum("PolicyBlocked")
        fallback_used = await _sum("FallbackUsed")
        errors = await _sum("StrategistError")
        deterministic = await _sum(
            "StrategistPath", [{"Name": "Path", "Value": "deterministic"}]
        )
        arbitration = await _sum(
            "StrategistPath", [{"Name": "Path", "Value": "haiku_arbitration"}]
        )

        # Vendor breakdown — short names emitted by the strategist layer.
        # These match the Vendor dimension the strategist sets when it calls
        # CloudWatch: "haiku", "sonnet", "opus".
        vendor_counts: dict[str, float] = {}
        for vendor in ("haiku", "sonnet", "opus"):
            count = await _sum(
                "VendorSelection", [{"Name": "Vendor", "Value": vendor}]
            )
            if count > 0:
                vendor_counts[vendor] = count

        return StrategistMetrics(
            period_minutes=period_minutes,
            total=total,
            vendor_counts=vendor_counts,
            policy_blocked=policy_blocked,
            fallback_used=fallback_used,
            deterministic_route=deterministic,
            arbitration_route=arbitration,
            errors=errors,
        )

    async def redaction_metrics(self, period_minutes: int = 60) -> RedactionMetrics:
        start, end = _window(period_minutes)
        period_s = period_minutes * 60

        async def _sum(metric: str, dims: list[dict[str, str]] | None = None) -> float:
            pts = await self._get_metric_stats(metric, "Sum", period_s, start, end, dims)
            return _safe_sum(pts)

        total = await _sum("RedactionCount")
        total_entities = await _sum("EntityCount")

        entity_type_counts: dict[str, float] = {}
        for et in ("SG_NRIC", "SG_FIN", "SG_UEN", "SG_PASSPORT", "CREDIT_CARD", "IBAN_CODE"):
            count = await _sum("EntityTypeCount", [{"Name": "EntityType", "Value": et}])
            if count > 0:
                entity_type_counts[et] = count

        return RedactionMetrics(
            period_minutes=period_minutes,
            total_processed=total,
            total_entities_redacted=total_entities,
            entity_type_counts=entity_type_counts,
        )
