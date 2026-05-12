"""Orchestrator configuration."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OrchestratorConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ORCHESTRATOR_")

    # SQS
    sqs_incoming_url: str = Field(default="")
    sqs_escalation_url: str = Field(default="")
    sqs_poll_wait_seconds: int = Field(default=20, ge=0, le=20)
    sqs_max_messages: int = Field(default=10, ge=1, le=10)

    # Presidio sidecar
    presidio_url: str = Field(default="http://localhost:8080")
    presidio_timeout_s: float = Field(default=5.0)

    # Redis vault
    redis_url: str = Field(default="redis://localhost:6379")
    vault_ttl_seconds: int = Field(default=300)  # 5 minutes — security boundary

    # DynamoDB
    dynamodb_audit_table: str = Field(default="ai-router-audit-log")
    dynamodb_review_table: str = Field(default="ai-router-review-log")

    # Infrastructure
    aws_region: str = Field(default="ap-southeast-1")

    # Service port (health check endpoint)
    port: int = Field(default=8000)
