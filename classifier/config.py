"""Intent classifier configuration."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ClassifierConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CLASSIFIER_")

    # Fast path — embedding similarity
    fast_path_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    cohere_model_id: str = Field(default="cohere.embed-multilingual-v3")

    # Deep path — Sonnet
    sonnet_model_id: str = Field(default="apac.anthropic.claude-3-5-sonnet-20241022-v2:0")
    sonnet_max_tokens: int = Field(default=300)

    # Escalation threshold
    escalate_threshold: float = Field(default=0.6, ge=0.0, le=1.0)

    # Infrastructure
    bedrock_region: str = Field(default="ap-southeast-1")
    redis_url: str = Field(default="redis://localhost:6379")
    dynamodb_routing_table: str = Field(default="ai-router-routing-rules")
