"""Admin dashboard FastAPI application.

Starts shared service instances on lifespan and attaches them to app.state
so routers can retrieve them via request.app.state.

Write surfaces: routing rule editor, escalation queue actions, tier overrides.
IAM role denies: bedrock:*, sqs:SendMessage (incoming queue), dynamodb:DeleteItem.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from admin.auth import require_cognito_token
from admin.config import AdminConfig
from admin.routers import audit, escalations, health, metrics, routing_rules, test_console, vendors
from admin.services.cloudwatch import CloudWatchService
from admin.services.dynamo_admin import DynamoAdminService
from admin.services.redis_admin import RedisAdminService
from admin.services.sqs_admin import SQSAdminService
from bouncer.config import BouncerConfig
from classifier.classifier import Classifier
from classifier.config import ClassifierConfig
from shared.bedrock import BedrockRuntime
from shared.logging import configure, safe_log


_KEEPALIVE_INTERVAL_S: float = 20.0  # below typical idle-connection timeout on AWS NLBs


async def _bedrock_keepalive(bedrock: BedrockRuntime, model_id: str) -> None:
    """Ping Haiku every 20 s to keep the VPC endpoint connection alive."""
    while True:
        await asyncio.sleep(_KEEPALIVE_INTERVAL_S)
        try:
            await bedrock.invoke_model(
                model_id,
                {
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
        except Exception as exc:
            safe_log.warning("admin.bedrock.keepalive.failed", error_type=type(exc).__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    cfg = AdminConfig()
    configure()

    redis = RedisAdminService(cfg.redis_url)
    await redis.connect()

    application.state.config = cfg
    application.state.cloudwatch = CloudWatchService(cfg.cloudwatch_namespace, cfg.aws_region)
    application.state.dynamo = DynamoAdminService(
        routing_table=cfg.dynamodb_routing_table,
        audit_table=cfg.dynamodb_audit_table,
        region=cfg.aws_region,
    )
    application.state.sqs_admin = SQSAdminService(
        escalation_url=cfg.sqs_escalation_url,
        review_table=cfg.dynamodb_review_table,
        region=cfg.aws_region,
        visibility_seconds=cfg.sqs_escalation_visibility_seconds,
    )
    application.state.redis = redis

    bedrock = BedrockRuntime(region=cfg.aws_region)

    # Open persistent Bedrock connections and pre-warm them so the TLS handshake
    # cost is paid once at startup rather than on the first real Haiku request.
    # Two separate clients: one for the bouncer (Haiku) and one for the classifier
    # (Sonnet).  A long Sonnet call must not tie up the Haiku connection and cause
    # the next bouncer call to pay a fresh handshake.
    bouncer_cfg = BouncerConfig()
    bouncer_bedrock = BedrockRuntime(region=cfg.aws_region)
    try:
        await bedrock.connect()       # classifier / strategist Sonnet client
        await bouncer_bedrock.connect()  # bouncer Haiku client (isolated)
        await bouncer_bedrock.invoke_model(
            bouncer_cfg.haiku_model_id,
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        safe_log.info("admin.bedrock.warmup.complete")
    except Exception as exc:
        safe_log.warning("admin.bedrock.warmup.failed", error_type=type(exc).__name__)

    keepalive_task = asyncio.create_task(
        _bedrock_keepalive(bouncer_bedrock, bouncer_cfg.haiku_model_id)
    )

    classifier = Classifier(ClassifierConfig(), bedrock)
    await classifier.initialize()
    application.state.bedrock = bedrock
    application.state.bouncer_bedrock = bouncer_bedrock
    application.state.classifier = classifier

    safe_log.info("admin.started", service_name="admin")
    yield

    keepalive_task.cancel()
    await bedrock.close()
    await bouncer_bedrock.close()
    await redis.close()
    safe_log.info("admin.stopped", service_name="admin")


app = FastAPI(
    title="AI Router Admin",
    description="Operational dashboard — monitoring, escalation review, routing configuration.",
    lifespan=lifespan,
)

_auth = [Depends(require_cognito_token)]

app.include_router(health.router)  # unprotected — needed for ALB health checks
app.include_router(metrics.router, dependencies=_auth)
app.include_router(escalations.router, dependencies=_auth)
app.include_router(routing_rules.router, dependencies=_auth)
app.include_router(audit.router, dependencies=_auth)
app.include_router(test_console.router, dependencies=_auth)
app.include_router(vendors.router, dependencies=_auth)


@app.get("/health")
async def root_health() -> dict[str, str]:
    return {"status": "ok", "service": "admin"}
