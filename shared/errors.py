"""Typed exceptions for the AI Router pipeline."""

from __future__ import annotations


class AIRouterError(Exception):
    """Base for all AI Router errors."""


class BedrockError(AIRouterError):
    """Bedrock invocation returned an error or failed unexpectedly."""


class BedrockTimeout(BedrockError):
    """Bedrock call exceeded its allocated time budget."""


class RedisError(AIRouterError):
    """Redis operation failed."""


class PresidioError(AIRouterError):
    """Presidio sidecar returned an error or is unreachable."""


class EscalationError(AIRouterError):
    """Failed to write to the escalation queue."""


class PolicyViolationError(AIRouterError):
    """Request blocked by the policy engine."""


__all__ = [
    "AIRouterError",
    "BedrockError",
    "BedrockTimeout",
    "EscalationError",
    "PolicyViolationError",
    "PresidioError",
    "RedisError",
]
