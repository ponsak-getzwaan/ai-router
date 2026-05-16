"""Bouncer: orchestrates the rule gate and Haiku LLM classifier.

Tracks the 200ms total budget, calls the rule gate first, and passes the
remaining budget to the LLM classifier. See the sequence diagram in
docs/architecture.md §"Layer 1 — Bouncer".
"""

from __future__ import annotations

import time

import redis.asyncio as aioredis

from bouncer.config import BouncerConfig
from bouncer.llm_classifier import CloudWatchMetrics, LLMClassifier, MetricPublisher
from bouncer.rule_gate import RuleGate
from shared.bedrock import BedrockRuntime
from shared.logging import safe_log
from shared.models import BounceResult, BouncerLayer, PipelineEnvelope


class Bouncer:
    """Two-layer gate: rule gate (no LLM) followed by Haiku micro-classifier.

    The rule gate is the only path that returns allowed=False.
    The Haiku classifier always returns allowed=True (fail-open on any error).
    """

    def __init__(
        self,
        config: BouncerConfig,
        redis: aioredis.Redis,
        bedrock: BedrockRuntime,
        metrics: MetricPublisher | None = None,
    ) -> None:
        self._metrics: MetricPublisher = metrics or CloudWatchMetrics(
            config.cloudwatch_namespace, config.bedrock_region
        )
        self._rule_gate = RuleGate(config, redis)
        self._llm_classifier = LLMClassifier(config, bedrock, self._metrics)
        self._config = config

    async def bounce(self, envelope: PipelineEnvelope) -> BounceResult:
        """Run the full bouncer pipeline against the pipeline envelope.

        Never raises. On any unexpected error the request is allowed through
        (fail-open posture).
        """
        start = time.monotonic()

        # Phase 1: Rule gate — returns None on pass, BounceResult on hard reject.
        rule_result = await self._rule_gate.check(envelope)
        if rule_result is not None:
            elapsed_ms = (time.monotonic() - start) * 1000.0
            safe_log.info(
                "bouncer.rejected",
                allowed=False,
                layer=rule_result.layer,
                reason=rule_result.reason,
                rule_gate_latency_ms=elapsed_ms,
            )
            await self._metrics.put_count(
                "RequestCount", {"Layer": "bouncer", "Outcome": "rejected"}
            )
            await self._metrics.put_count("RequestCount", {"Layer": "bouncer"})
            return rule_result

        # Phase 2: Haiku LLM classifier with whatever budget remains.
        elapsed_ms = (time.monotonic() - start) * 1000.0
        remaining_ms = self._config.total_budget_ms - elapsed_ms

        if remaining_ms <= 0:
            # Rule gate somehow consumed the entire budget. Shouldn't happen
            # (rule gate is microseconds), but fail open if it does.
            safe_log.warning(
                "bouncer.rule_gate.budget_overrun",
                error_type="BudgetOverrun",
                timed_out=True,
                rule_gate_latency_ms=elapsed_ms,
            )
            await self._metrics.put_count("BouncerTimeout", {"Layer": "bouncer"})
            await self._metrics.put_count("RequestCount", {"Layer": "bouncer"})
            return BounceResult(
                allowed=True,
                reason="budget_overrun_fail_open",
                layer=BouncerLayer.TIMEOUT_FAIL_OPEN,
                confidence=0.0,
                timed_out=True,
            )

        result = await self._llm_classifier.classify(envelope, remaining_budget_ms=remaining_ms)

        total_ms = (time.monotonic() - start) * 1000.0
        safe_log.info(
            "bouncer.completed",
            allowed=result.allowed,
            escalate=result.escalate,
            confidence=result.confidence,
            timed_out=result.timed_out,
            total_latency_ms=total_ms,
        )

        outcome = "escalated" if result.escalate else "passed"
        await self._metrics.put_count(
            "RequestCount", {"Layer": "bouncer", "Outcome": outcome}
        )
        # Aggregate total (no Outcome dimension) — what the dashboard shows as "Total requests"
        await self._metrics.put_count("RequestCount", {"Layer": "bouncer"})

        return result


__all__ = ["Bouncer"]
