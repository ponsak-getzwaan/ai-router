"""Routing strategist configuration."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class StrategistConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STRATEGIST_")

    # Confidence thresholds (CLAUDE.md §7 Strategist)
    deterministic_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    escalate_threshold: float = Field(default=0.5, ge=0.0, le=1.0)

    # Haiku arbitration
    haiku_model_id: str = Field(default="apac.anthropic.claude-3-haiku-20240307-v1:0")
    haiku_max_tokens: int = Field(default=80)

    # Default vendor when no rule matches
    default_vendor: str = Field(default="apac.anthropic.claude-sonnet-4-20250514-v1:0")

    # Timeouts (seconds) used in the RoutingContext
    haiku_timeout_s: float = Field(default=15.0)
    sonnet_timeout_s: float = Field(default=30.0)

    # Infrastructure
    bedrock_region: str = Field(default="ap-southeast-1")
    dynamodb_routing_table: str = Field(default="ai-router-routing-rules")
