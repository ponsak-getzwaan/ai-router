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
from orchestrator.history import SessionHistory
from orchestrator.pipeline_driver import PipelineDriver
from orchestrator.presidio_client import PresidioClient
from orchestrator.sqs_consumer import SQSConsumer
from shared.bedrock import BedrockRuntime, get_bedrock_runtime
from shared.logging import configure, safe_log
from strategist.config import StrategistConfig
from strategist.strategist import Strategist

configure(json_output=True)

_KEEPALIVE_INTERVAL_S: float = 20.0

_config = OrchestratorConfig()
_consumer: SQSConsumer | None = None


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
            safe_log.warning("orchestrator.bedrock.keepalive.failed", error_type=type(exc).__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _consumer  # noqa: PLW0603

    bouncer_cfg = BouncerConfig()
    redis: aioredis.Redis = aioredis.from_url(_config.redis_url, decode_responses=False)  # type: ignore[no-untyped-call]

    # Two isolated Bedrock clients: bouncer_bedrock (Haiku) and bedrock (Sonnet/Cohere).
    # Isolation prevents long Sonnet calls from disrupting the Haiku connection pool.
    bedrock = get_bedrock_runtime()
    bouncer_bedrock = BedrockRuntime(region=_config.aws_region)
    try:
        await bedrock.connect()
        await bouncer_bedrock.connect()
        await bouncer_bedrock.invoke_model(
            bouncer_cfg.haiku_model_id,
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        safe_log.info("orchestrator.bedrock.warmup.complete")
    except Exception as exc:
        safe_log.warning("orchestrator.bedrock.warmup.failed", error_type=type(exc).__name__)

    keepalive_task = asyncio.create_task(
        _bedrock_keepalive(bouncer_bedrock, bouncer_cfg.haiku_model_id)
    )

    presidio = PresidioClient(_config.presidio_url, _config.presidio_timeout_s)
    bouncer = Bouncer(bouncer_cfg, redis, bouncer_bedrock)
    classifier = Classifier(ClassifierConfig(), bedrock)
    strategist = Strategist(StrategistConfig(), bedrock)
    audit = AuditLogger(_config.dynamodb_audit_table, _config.aws_region)
    history = SessionHistory(redis)

    driver = PipelineDriver(
        presidio=presidio,
        redis=redis,
        bouncer=bouncer,
        classifier=classifier,
        strategist=strategist,
        audit=audit,
        history=history,
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
    keepalive_task.cancel()
    await presidio.aclose()
    await bouncer_bedrock.close()
    await redis.aclose()

    safe_log.info("orchestrator.stopped", service_name="orchestrator")


app = FastAPI(title="AI Router Orchestrator", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
