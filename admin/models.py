"""Pydantic response models for the admin dashboard API.

All models that surface user-originated data must pass through the redacted
representation only — never raw messages, never vault tokens.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Out(BaseModel):
    """Base: mutable (responses don't need immutability), no extras."""

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class ServiceHealth(_Out):
    status: str  # "ok" | "degraded" | "unavailable"
    dynamodb: str
    redis: str
    sqs: str
    checked_at: datetime


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class LatencyPercentiles(_Out):
    p50: float | None
    p99: float | None
    p999: float | None


class PipelineMetrics(_Out):
    period_minutes: int
    total_requests: float
    error_rate_pct: float | None
    escalation_rate_pct: float | None
    latency_ms: LatencyPercentiles


class BouncerMetrics(_Out):
    period_minutes: int
    total: float
    passed: float
    rejected: float
    escalated: float
    timed_out: float
    errors: float
    pass_rate_pct: float | None
    avg_confidence: float | None


class ClassifierMetrics(_Out):
    period_minutes: int
    total: float
    fast_path: float
    deep_path: float
    escalated: float
    intent_counts: dict[str, float]


class RedactionMetrics(_Out):
    period_minutes: int
    total_processed: float
    total_entities_redacted: float
    entity_type_counts: dict[str, float]


class StrategistMetrics(_Out):
    period_minutes: int
    total: float
    vendor_counts: dict[str, float]   # short vendor name → selection count
    policy_blocked: float             # times policy engine vetoed a vendor
    fallback_used: float              # times fallback vendor was chosen
    deterministic_route: float        # conf ≥ 0.85 → direct rule lookup
    arbitration_route: float          # Haiku arbitration used
    errors: float


# ---------------------------------------------------------------------------
# Escalations
# ---------------------------------------------------------------------------


class EscalationMessage(_Out):
    """Represents a message pending human review.

    `redacted_preview` is the Presidio-redacted text — never the raw message
    or de-tokenised text. Vault tokens are not surfaced here.
    """

    receipt_handle: str = Field(description="SQS receipt handle — needed for approve/reject.")
    message_id: str
    correlation_id: str
    user_sub: str
    session_id: str
    redacted_preview: str = Field(description="Presidio-redacted text only, never raw.")
    entity_types: list[str]
    bouncer_reason: str | None
    sent_at: datetime | None
    approximate_receive_count: int


class EscalationList(_Out):
    messages: list[EscalationMessage]
    queue_depth: int


class EscalationAction(_Out):
    message_id: str
    action: str  # "approved" | "rejected" | "requeued"
    correlation_id: str
    annotation: str | None


# ---------------------------------------------------------------------------
# Routing rules
# ---------------------------------------------------------------------------


class RoutingRule(_Out):
    intent: str
    vendor: str
    fallback: str | None
    description: str | None


class RoutingRuleUpdate(_Out):
    vendor: str = Field(min_length=1, max_length=200)
    fallback: str | None = None
    description: str | None = Field(default=None, max_length=500)


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


class AuditRecord(_Out):
    """One row from the audit log.

    Contains entity type names and counts only — never values, never raw
    or redacted message text (architecture.md §end-to-end sequence step 10).
    """

    correlation_id: str
    timestamp: str
    user_sub: str
    session_id: str
    entity_types_redacted: list[str]
    entity_count: int
    was_redacted: bool
    bouncer_allowed: bool | None
    bouncer_escalated: bool | None
    intent: str | None
    intent_confidence: str | None
    intent_escalated: bool | None = None
    vendor: str | None
    routing_path: str | None
    policy_blocked: bool | None
    total_latency_ms: str | None
    error_type: str | None
    vendor_response_redacted: str | None = None


class AuditQuery(_Out):
    records: list[AuditRecord]
    count: int
    last_evaluated_key: dict[str, Any] | None


# ---------------------------------------------------------------------------
# Test console
# ---------------------------------------------------------------------------


class TestConsoleRequest(_Out):
    """Input for the test console.

    Accepts a raw message. Presidio redaction runs inside the Orchestrator
    before any LLM call — PII is never stored or sent to the vendor.
    """

    message: str = Field(
        min_length=1,
        max_length=4096,
        description="Raw message — Presidio redaction runs before any LLM call.",
    )
    user_sub: str = Field(
        default="admin-test-user",
        min_length=1,
        max_length=128,
    )
    session_id: str = Field(default="admin-test-session", min_length=1, max_length=128)


class TestConsoleLayerResult(_Out):
    layer: str
    latency_ms: float
    outcome: dict[str, Any]


class TestConsoleResponse(_Out):
    correlation_id: str
    layers: list[TestConsoleLayerResult]
    final_vendor: str | None
    total_latency_ms: float
    timed_out: bool
    error: str | None
    response: str | None = None
