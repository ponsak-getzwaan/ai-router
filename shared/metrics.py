"""CloudWatch metric emission helpers for pipeline layers.

Fire-and-forget: callers use asyncio.create_task() so metrics don't
add latency to the hot path. Failures are logged at warning level only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import aioboto3  # type: ignore[import-untyped]

from shared.logging import safe_log

if TYPE_CHECKING:
    from shared.models import ClassifiedIntent, RoutingPlan

_NAMESPACE = "AIRouter"
_session: aioboto3.Session = aioboto3.Session()


async def _emit(metric_data: list[dict[str, Any]], region: str) -> None:
    try:
        async with _session.client("cloudwatch", region_name=region) as cw:
            await cw.put_metric_data(Namespace=_NAMESPACE, MetricData=metric_data)
    except Exception as exc:
        safe_log.warning("metrics.emit_error", error_type=type(exc).__name__)


def _short_vendor(vendor_id: str) -> str:
    if "haiku" in vendor_id:
        return "haiku"
    if "sonnet" in vendor_id:
        return "sonnet"
    return "other"


async def emit_classifier(intent: "ClassifiedIntent", region: str) -> None:
    data: list[dict[str, Any]] = [
        {
            "MetricName": "RequestCount",
            "Dimensions": [{"Name": "Layer", "Value": "classifier"}],
            "Value": 1,
            "Unit": "Count",
        },
        {
            "MetricName": "ClassifierPath",
            "Dimensions": [{"Name": "Path", "Value": intent.path}],
            "Value": 1,
            "Unit": "Count",
        },
    ]
    if intent.escalate:
        data.append({
            "MetricName": "RequestCount",
            "Dimensions": [
                {"Name": "Layer", "Value": "classifier"},
                {"Name": "Outcome", "Value": "escalated"},
            ],
            "Value": 1,
            "Unit": "Count",
        })
    else:
        data.append({
            "MetricName": "IntentCount",
            "Dimensions": [{"Name": "Intent", "Value": intent.intent}],
            "Value": 1,
            "Unit": "Count",
        })
    await _emit(data, region)


async def emit_strategist(plan: "RoutingPlan", region: str) -> None:
    data: list[dict[str, Any]] = [
        {
            "MetricName": "RequestCount",
            "Dimensions": [{"Name": "Layer", "Value": "strategist"}],
            "Value": 1,
            "Unit": "Count",
        },
        {
            "MetricName": "StrategistPath",
            "Dimensions": [{"Name": "Path", "Value": plan.path}],
            "Value": 1,
            "Unit": "Count",
        },
    ]
    if plan.blocked:
        data.append({
            "MetricName": "PolicyBlocked",
            "Dimensions": [],
            "Value": 1,
            "Unit": "Count",
        })
    else:
        data.append({
            "MetricName": "VendorSelection",
            "Dimensions": [{"Name": "Vendor", "Value": _short_vendor(plan.primary_vendor)}],
            "Value": 1,
            "Unit": "Count",
        })
    await _emit(data, region)


__all__ = ["emit_classifier", "emit_strategist"]
