"""Haiku LLM micro-classifier: second sublayer of the Bouncer.

Calls Claude Haiku via Bedrock to assess message safety.

CRITICAL INVARIANT: This layer NEVER blocks a request. On timeout or any
Bedrock error, it fails open (allowed=True, timed_out=True). The only hard
block comes from the rule gate. See CLAUDE.md §3.4 and the Bouncer sequence
diagram in docs/architecture.md.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Protocol, runtime_checkable

import aioboto3  # type: ignore[import-untyped]

from bouncer.config import BouncerConfig
from shared.bedrock import BedrockRuntime
from shared.errors import BedrockError
from shared.logging import safe_log
from shared.models import BounceResult, BouncerLayer, PipelineEnvelope

_SYSTEM_PROMPT = (
    "Assess if this message is safe to process. "
    'Reply with JSON only, no other text: {"pass": true|false, '
    '"reason": "safe|toxic|harmful|spam|unclear", "confidence": 0.0-1.0}'
)


@runtime_checkable
class MetricPublisher(Protocol):
    """Publishes a single count metric. Injected for testability."""

    async def put_count(
        self, metric_name: str, dimensions: dict[str, str] | None = None
    ) -> None: ...


class CloudWatchMetrics:
    """Publishes count metrics to CloudWatch. Best-effort; never raises."""

    def __init__(self, namespace: str, region: str) -> None:
        self._namespace = namespace
        self._region = region
        self._session: aioboto3.Session = aioboto3.Session()

    async def put_count(
        self, metric_name: str, dimensions: dict[str, str] | None = None
    ) -> None:
        dims = [{"Name": k, "Value": v} for k, v in (dimensions or {}).items()]
        try:
            async with self._session.client("cloudwatch", region_name=self._region) as cw:
                await cw.put_metric_data(
                    Namespace=self._namespace,
                    MetricData=[{
                        "MetricName": metric_name,
                        "Value": 1,
                        "Unit": "Count",
                        "Dimensions": dims,
                    }],
                )
        except Exception as exc:
            safe_log.warning("bouncer.cloudwatch.error", error_type=type(exc).__name__)


class LLMClassifier:
    """Haiku-based safety classifier with fail-open timeout and error handling."""

    def __init__(
        self,
        config: BouncerConfig,
        bedrock: BedrockRuntime,
        metrics: MetricPublisher,
    ) -> None:
        self._config = config
        self._bedrock = bedrock
        self._metrics = metrics

    async def classify(
        self, envelope: PipelineEnvelope, remaining_budget_ms: float
    ) -> BounceResult:
        """Classify the message using Haiku. Never raises — always returns a BounceResult."""
        budget_s = remaining_budget_ms / 1000.0
        # Use asyncio.shield so the underlying Bedrock HTTP request is NOT cancelled on
        # timeout. Cancelling an aioboto3 client mid-flight corrupts the shared connection
        # pool, causing every subsequent call to fail. shield() lets the task finish
        # normally in the background so connections are returned cleanly to the pool.
        task: asyncio.Task[BounceResult] = asyncio.create_task(self._invoke(envelope))
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=budget_s)
        except TimeoutError:
            # Retrieve the eventual result/exception so Python doesn't log
            # "Task exception was never retrieved" when the background task finishes.
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
            safe_log.warning(
                "bouncer.haiku.timeout",
                error_type="TimeoutError",
                timed_out=True,
                allowed=True,
            )
            await self._metrics.put_count("BouncerTimeout", {"Layer": "bouncer"})
            return BounceResult(
                allowed=True,
                reason="haiku_timeout_fail_open",
                layer=BouncerLayer.TIMEOUT_FAIL_OPEN,
                confidence=0.0,
                timed_out=True,
            )
        except BedrockError as exc:
            task.cancel()
            safe_log.warning(
                "bouncer.haiku.bedrock_error",
                error_type=type(exc).__name__,
                allowed=True,
            )
            await self._metrics.put_count("BouncerError", {"Layer": "bouncer"})
            return BounceResult(
                allowed=True,
                reason="haiku_error_fail_open",
                layer=BouncerLayer.TIMEOUT_FAIL_OPEN,
                confidence=0.0,
                timed_out=False,
            )

    async def _invoke(self, envelope: PipelineEnvelope) -> BounceResult:
        """Call Bedrock Haiku and parse the safety verdict."""
        body: dict[str, Any] = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": self._config.haiku_max_tokens,
            "system": _SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": envelope.redacted_message}],
        }

        response = await self._bedrock.invoke_model(self._config.haiku_model_id, body)

        # Parse Anthropic Messages API response format.
        # If the response is malformed, re-raise as BedrockError so classify()
        # catches it and fails open.
        try:
            text: str = response["content"][0]["text"]
            parsed: dict[str, Any] = json.loads(text)
            haiku_pass: bool = bool(parsed.get("pass", False))
            raw_reason: str = str(parsed.get("reason", "unclear"))[:50]
            confidence: float = max(0.0, min(1.0, float(parsed.get("confidence", 0.0))))
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise BedrockError(type(exc).__name__) from exc

        # Strip characters that would fail BounceResult's reason validator.
        reason = raw_reason.replace("\n", " ").replace("@", "").strip() or "unclear"

        # escalate=True when Haiku says unsafe OR confidence is too low.
        # The LLM classifier never sets allowed=False — only the rule gate does.
        escalate = not haiku_pass or confidence < self._config.confidence_threshold

        safe_log.info(
            "bouncer.haiku.verdict",
            allowed=True,
            escalate=escalate,
            confidence=confidence,
        )

        return BounceResult(
            allowed=True,
            reason=reason,
            layer=BouncerLayer.LLM_CLASSIFIER,
            confidence=confidence,
            escalate=escalate,
        )


__all__ = ["CloudWatchMetrics", "LLMClassifier", "MetricPublisher"]
