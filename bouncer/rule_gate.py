"""Rule-based gate: first sublayer of the Bouncer.

Pure Python, no LLM. Designed to complete in single-digit milliseconds.
Four checks in order: message length → prompt injection → banned user → rate limit.

Returns BounceResult(allowed=False) on first failure.
Returns None if all checks pass (caller proceeds to LLM classifier).

See docs/architecture.md §"Layer 1 — Bouncer" sequence diagram.
"""

from __future__ import annotations

import re

import redis.asyncio as aioredis

from bouncer.config import BouncerConfig
from shared.logging import safe_log
from shared.models import BounceResult, BouncerLayer, PipelineEnvelope

# Regex patterns indicating prompt injection attempts.
# Evaluated against the REDACTED message — injection attempts typically don't
# rely on PII, so redaction tokens don't hide them.
_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bignore\s+(previous|all|prior)\s+instructions?\b", re.IGNORECASE),
    re.compile(r"\bdisregard\s+(your|all|previous)\b", re.IGNORECASE),
    re.compile(r"\byou\s+are\s+now\s+\w", re.IGNORECASE),
    re.compile(r"\bact\s+as\s+(?:if\s+)?(?:you\s+are|a|an)\s+\w", re.IGNORECASE),
    re.compile(r"\bnew\s+system\s+(?:instructions?|prompt)\b", re.IGNORECASE),
    re.compile(r"\bjailbreak\b", re.IGNORECASE),
    re.compile(r"<\s*/?system\s*>", re.IGNORECASE),
    re.compile(r"\bDAN\b"),
    re.compile(r"\bprompt\s+injection\b", re.IGNORECASE),
)

_BANNED_KEY_PREFIX = "banned:"
_RATE_KEY_PREFIX = "ratelimit:"
_RATE_WINDOW_SECONDS = 60


class RuleGate:
    """Synchronous checks wrapped in async for pipeline uniformity.

    Redis is used for the banned-user and rate-limit checks only.
    Length and injection checks are pure in-process Python.
    """

    def __init__(self, config: BouncerConfig, redis: aioredis.Redis) -> None:
        self._config = config
        self._redis = redis

    async def check(self, envelope: PipelineEnvelope) -> BounceResult | None:
        """Run all rule checks in order.

        Returns:
            BounceResult(allowed=False, ...) on the first failing check.
            None if all checks pass — caller should proceed to LLM classifier.
        """
        message = envelope.redacted_message
        user_sub = envelope.user_sub

        # 1. Length check (no I/O — fast)
        if len(message) > self._config.max_message_length:
            safe_log.warning(
                "bouncer.rule_gate.rejected",
                user_sub=user_sub,
                allowed=False,
                reason="message_too_long",
            )
            return BounceResult(
                allowed=False,
                reason="message_too_long",
                layer=BouncerLayer.RULE_GATE,
                confidence=1.0,
            )

        # 2. Prompt injection patterns (no I/O — fast)
        for pattern in _INJECTION_PATTERNS:
            if pattern.search(message):
                safe_log.warning(
                    "bouncer.rule_gate.rejected",
                    user_sub=user_sub,
                    allowed=False,
                    reason="prompt_injection_detected",
                )
                return BounceResult(
                    allowed=False,
                    reason="prompt_injection_detected",
                    layer=BouncerLayer.RULE_GATE,
                    confidence=1.0,
                )

        # 3. Banned user check (one Redis GET)
        banned_value = await self._redis.get(f"{_BANNED_KEY_PREFIX}{user_sub}")
        if banned_value is not None:
            safe_log.warning(
                "bouncer.rule_gate.rejected",
                user_sub=user_sub,
                allowed=False,
                reason="user_banned",
            )
            return BounceResult(
                allowed=False,
                reason="user_banned",
                layer=BouncerLayer.RULE_GATE,
                confidence=1.0,
            )

        # 4. Rate limit (INCR + conditional EXPIRE — one round-trip each)
        rate_key = f"{_RATE_KEY_PREFIX}{user_sub}"
        count: int = await self._redis.incr(rate_key)
        if count == 1:
            # Set TTL only on the first request in each window.
            # Race condition (two simultaneous first-requests) is harmless:
            # both will set TTL=60, which is the correct behaviour.
            await self._redis.expire(rate_key, _RATE_WINDOW_SECONDS)
        if count > self._config.rate_limit_per_minute:
            safe_log.warning(
                "bouncer.rule_gate.rejected",
                user_sub=user_sub,
                allowed=False,
                reason="rate_limit_exceeded",
            )
            return BounceResult(
                allowed=False,
                reason="rate_limit_exceeded",
                layer=BouncerLayer.RULE_GATE,
                confidence=1.0,
            )

        safe_log.info(
            "bouncer.rule_gate.passed",
            user_sub=user_sub,
            allowed=True,
        )
        return None
