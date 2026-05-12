"""GET /admin/metrics/* — CloudWatch metrics for each pipeline layer."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from admin.models import BouncerMetrics, ClassifierMetrics, PipelineMetrics, RedactionMetrics
from admin.services.cloudwatch import CloudWatchService

router = APIRouter(prefix="/admin/metrics", tags=["metrics"])


def _cw(request: Request) -> CloudWatchService:
    return request.app.state.cloudwatch


@router.get("/pipeline", response_model=PipelineMetrics)
async def pipeline_metrics(
    request: Request,
    period_minutes: int = Query(default=60, ge=5, le=1440),
) -> PipelineMetrics:
    return await _cw(request).pipeline_metrics(period_minutes)


@router.get("/bouncer", response_model=BouncerMetrics)
async def bouncer_metrics(
    request: Request,
    period_minutes: int = Query(default=60, ge=5, le=1440),
) -> BouncerMetrics:
    return await _cw(request).bouncer_metrics(period_minutes)


@router.get("/classifier", response_model=ClassifierMetrics)
async def classifier_metrics(
    request: Request,
    period_minutes: int = Query(default=60, ge=5, le=1440),
) -> ClassifierMetrics:
    return await _cw(request).classifier_metrics(period_minutes)


@router.get("/redaction", response_model=RedactionMetrics)
async def redaction_metrics(
    request: Request,
    period_minutes: int = Query(default=60, ge=5, le=1440),
) -> RedactionMetrics:
    return await _cw(request).redaction_metrics(period_minutes)
