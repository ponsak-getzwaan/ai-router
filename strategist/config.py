"""Routing strategist configuration."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class StrategistConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STRATEGIST_")

    # Confidence thresholds (CLAUDE.md §7 Strategist)
    deterministic_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    escalate_threshold: float = Field(default=0.5, ge=0.0, le=1.0)

    # Haiku arbitration
    haiku_model_id: str = Field(default="apac.anthropic.claude-haiku-4-5-20241022-v1:0")
    haiku_max_tokens: int = Field(default=80)

    # Default vendor when no rule matches
    default_vendor: str = Field(default="apac.anthropic.claude-sonnet-4-6-20241022-v2:0")

    # Timeouts (seconds) used in the RoutingContext
    haiku_timeout_s: float = Field(default=3.0)
    sonnet_timeout_s: float = Field(default=8.0)

    # Infrastructure
    bedrock_region: str = Field(default="ap-southeast-1")
    dynamodb_routing_table: str = Field(default="ai-router-routing-rules")
