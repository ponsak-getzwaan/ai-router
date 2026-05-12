"""Admin dashboard configuration."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AdminConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ADMIN_")

    # AWS
    aws_region: str = Field(default="ap-southeast-1")

    # DynamoDB
    dynamodb_routing_table: str = Field(default="ai-router-routing-rules")
    dynamodb_audit_table: str = Field(default="ai-router-audit-log")
    dynamodb_review_table: str = Field(default="ai-router-review-log")

    # SQS
    sqs_escalation_url: str = Field(default="")
    sqs_escalation_visibility_seconds: int = Field(default=300)

    # Redis (aggregate stats only — no vault reads allowed)
    redis_url: str = Field(default="redis://localhost:6379")

    # CloudWatch namespace
    cloudwatch_namespace: str = Field(default="AIRouter")

    # Service
    port: int = Field(default=8000)
    environment: str = Field(default="prod")
