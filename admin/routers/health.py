"""GET /admin/health — checks reachability of DynamoDB, Redis, and SQS."""

from __future__ import annotations

from datetime import UTC, datetime

import aioboto3  # type: ignore[import-untyped]
from fastapi import APIRouter, Request

from admin.models import ServiceHealth
from admin.services.redis_admin import RedisAdminService
from shared.logging import safe_log

router = APIRouter(prefix="/admin/api", tags=["health"])


@router.get("/health", response_model=ServiceHealth)
async def health(request: Request) -> ServiceHealth:
    cfg = request.app.state.config
    session: aioboto3.Session = aioboto3.Session()

    # DynamoDB — Scan with Limit=1 exercises the data path without needing
    # dynamodb:DescribeTable, which the admin IAM role does not have.
    dynamo_status = "ok"
    try:
        async with session.client("dynamodb", region_name=cfg.aws_region) as ddb:
            await ddb.scan(TableName=cfg.dynamodb_routing_table, Limit=1)
    except Exception as exc:
        safe_log.warning("admin.health.dynamo_error", error_type=type(exc).__name__)
        dynamo_status = "unavailable"

    # SQS
    sqs_status = "ok"
    if cfg.sqs_escalation_url:
        try:
            async with session.client("sqs", region_name=cfg.aws_region) as sqs:
                await sqs.get_queue_attributes(
                    QueueUrl=cfg.sqs_escalation_url,
                    AttributeNames=["ApproximateNumberOfMessages"],
                )
        except Exception as exc:
            safe_log.warning("admin.health.sqs_error", error_type=type(exc).__name__)
            sqs_status = "unavailable"
    else:
        sqs_status = "not_configured"

    # Redis
    redis_svc: RedisAdminService = request.app.state.redis
    redis_status = await redis_svc.health()

    overall = (
        "ok"
        if dynamo_status == "ok" and redis_status == "ok"
        else "degraded"
    )

    return ServiceHealth(
        status=overall,
        dynamodb=dynamo_status,
        redis=redis_status,
        sqs=sqs_status,
        checked_at=datetime.now(UTC),
    )
