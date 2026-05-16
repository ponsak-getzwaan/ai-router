"""Bouncer configuration loaded from environment variables.

All tuneable knobs live here. Hardcoding values in logic files is forbidden —
use this config so thresholds can be changed without redeployment.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BouncerConfig(BaseSettings):
    """Environment-driven configuration for the Bouncer layer.

    Env var prefix: BOUNCER_  (e.g. BOUNCER_TOTAL_BUDGET_MS=150)
    """

    model_config = SettingsConfigDict(env_prefix="BOUNCER_")

    # -------------------------------------------------------------------------
    # Time budget
    # -------------------------------------------------------------------------
    total_budget_ms: float = Field(
        default=200.0,
        gt=0,
        description="Total time budget for rule gate + Haiku, in milliseconds.",
    )

    # -------------------------------------------------------------------------
    # Haiku LLM micro-classifier
    # -------------------------------------------------------------------------
    haiku_model_id: str = Field(
        default="apac.anthropic.claude-haiku-4-5-20241022-v1:0",
        description=(
            "Bedrock cross-region inference profile ID. "
            "Verify the exact ID in the Bedrock console before pinning. "
            "Raw model IDs fail with 'on-demand throughput not supported'."
        ),
    )
    haiku_max_tokens: int = Field(default=50, gt=0, le=100)
    confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Haiku confidence below this value → escalate to human review.",
    )

    # -------------------------------------------------------------------------
    # Rule gate
    # -------------------------------------------------------------------------
    max_message_length: int = Field(
        default=4096,
        gt=0,
        description="Maximum allowed length of the redacted message in characters.",
    )
    rate_limit_per_minute: int = Field(
        default=60,
        gt=0,
        description="Maximum requests per user per 60-second fixed window.",
    )

    # -------------------------------------------------------------------------
    # Infrastructure
    # -------------------------------------------------------------------------
    redis_url: str = Field(default="redis://localhost:6379")
    bedrock_region: str = Field(default="ap-southeast-1")
    cloudwatch_namespace: str = Field(default="AIRouter")
