"""Orchestrator entry point.

FastAPI app provides the /health endpoint for ECS health checks.
The SQS consumer runs as a background asyncio task.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI

from bouncer.bouncer import Bouncer
from bouncer.config import BouncerConfig
from classifier.classifier import Classifier
from classifier.config import ClassifierConfig
from orchestrator.audit import AuditLogger
from orchestrator.config import OrchestratorConfig
from orchestrator.pipeline_driver import PipelineDriver
from orchestrator.presidio_client import PresidioClient
from orchestrator.sqs_consumer import SQSConsumer
from shared.bedrock import get_bedrock_runtime
from shared.logging import configure, safe_log
from strategist.config import StrategistConfig
from strategist.strategist import Strategist

configure(json_output=True)

_config = OrchestratorConfig()
_consumer: SQSConsumer | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _consumer  # noqa: PLW0603

    bedrock = get_bedrock_runtime()
    redis: aioredis.Redis = aioredis.from_url(_config.redis_url, decode_responses=False)  # type: ignore[no-untyped-call]

    presidio = PresidioClient(_config.presidio_url, _config.presidio_timeout_s)
    bouncer = Bouncer(BouncerConfig(), redis, bedrock)
    classifier = Classifier(ClassifierConfig(), bedrock)
    strategist = Strategist(StrategistConfig(), bedrock)
    audit = AuditLogger(_config.dynamodb_audit_table, _config.aws_region)

    driver = PipelineDriver(
        presidio=presidio,
        redis=redis,
        bouncer=bouncer,
        classifier=classifier,
        strategist=strategist,
        audit=audit,
        vault_ttl_seconds=_config.vault_ttl_seconds,
        sqs_escalation_url=_config.sqs_escalation_url,
        aws_region=_config.aws_region,
    )

    _consumer = SQSConsumer(_config, driver)
    consumer_task = asyncio.create_task(_consumer.start())

    safe_log.info("orchestrator.started", service_name="orchestrator")

    yield

    # Shutdown
    if _consumer:
        await _consumer.stop()
    consumer_task.cancel()
    await presidio.aclose()
    await redis.aclose()

    safe_log.info("orchestrator.stopped", service_name="orchestrator")


app = FastAPI(title="AI Router Orchestrator", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
