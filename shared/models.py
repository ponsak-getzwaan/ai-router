"""Pydantic v2 handoff contracts for the AI Router pipeline.

Every type that crosses a layer boundary lives here. Layers MUST NOT define
their own copies of these types — that's how taxonomies drift.

Source of truth: docs/architecture.md §"Key handoff contracts".

All models:
  - Are immutable (`frozen=True`) — once a layer emits a result, the next
    layer can't mutate it.
  - Forbid extra fields (`extra="forbid"`) — silent field drops are a class
    of bug we want to catch immediately.
  - Use `model_config` rather than the deprecated `Config` inner class.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# =============================================================================
# Enums
# =============================================================================


class BouncerLayer(StrEnum):
    """Which sub-layer of the Bouncer produced a verdict."""

    RULE_GATE = "rule_gate"
    LLM_CLASSIFIER = "llm_classifier"
    TIMEOUT_FAIL_OPEN = "timeout_fail_open"


class IntentDomain(StrEnum):
    """Top-level intent domain.

    These are the placeholder values from docs/architecture.md until the
    final taxonomy is committed. See docs/intent-taxonomy.md.
    """

    GENERAL_QA = "general_qa"
    CODE_ASSISTANCE = "code_assistance"
    SIMPLE_TRANSACTIONAL = "simple_transactional"
    OUT_OF_SCOPE = "out_of_scope"
    AMBIGUOUS = "ambiguous"


class ClassifierPath(StrEnum):
    """Which classifier path produced the verdict."""

    FAST = "fast"  # Bedrock Titan embedding similarity
    DEEP = "deep"  # Sonnet + MCP tools


class StrategistPath(StrEnum):
    """Which strategist path produced the routing plan."""

    DETERMINISTIC = "deterministic"  # confidence >= 0.85
    HAIKU_ARBITRATION = "haiku_arbitration"  # 0.5 <= confidence < 0.85
    ESCALATED = "escalated"  # confidence < 0.5


class EntityType(StrEnum):
    """Entity types known to the redactor.

    The Singapore-specific recognisers are required (see
    docs/architecture.md §"PII redaction"). Generic types are Presidio defaults.
    """

    # Singapore-specific (high-sensitivity, always redacted)
    SG_NRIC = "SG_NRIC"
    SG_FIN = "SG_FIN"
    SG_UEN = "SG_UEN"
    SG_PASSPORT = "SG_PASSPORT"

    # Generic (high-sensitivity, always redacted)
    CREDIT_CARD = "CREDIT_CARD"
    IBAN_CODE = "IBAN_CODE"
    LARGE_CURRENCY = "LARGE_CURRENCY"

    # Generic (contextual, NOT redacted by default — see Position C)
    LOCATION = "LOCATION"
    PERSON = "PERSON"
    DATE_TIME = "DATE_TIME"
    PHONE_NUMBER = "PHONE_NUMBER"
    EMAIL_ADDRESS = "EMAIL_ADDRESS"


# =============================================================================
# Type aliases for clarity
# =============================================================================

CorrelationID = Annotated[
    UUID,
    Field(
        description="Threads through every log line, queue message, and trace span.",
    ),
]

UserSub = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        description="Cognito UUID. Never email or any PII-bearing claim.",
    ),
]

Confidence = Annotated[
    float,
    Field(ge=0.0, le=1.0, description="0.0 (no confidence) to 1.0 (certain)."),
]


# =============================================================================
# Base
# =============================================================================


class _Frozen(BaseModel):
    """Base config: immutable + strict.

    All handoff types inherit from this. Mutating a result after creation
    breaks pipeline invariants — keep the type system on our side.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


# =============================================================================
# Layer 1 — Bouncer
# =============================================================================


class BounceResult(_Frozen):
    """Verdict from the Bouncer (rule gate + Haiku classifier).

    See CLAUDE.md §7 "Bouncer" for the fail-open semantics:
      - On timeout, `allowed=True`, `timed_out=True`, `escalate=False`.
        The request goes through; a CloudWatch metric records the timeout.
      - The natural code is the wrong code here. Test the timeout path.
    """

    allowed: bool = Field(description="Whether the request may proceed downstream.")
    reason: str = Field(
        min_length=1,
        max_length=200,
        description="Short reason code, not a message body.",
    )
    layer: BouncerLayer
    confidence: Confidence
    escalate: bool = Field(
        default=False,
        description="True if the request should also be logged to the Review Log.",
    )
    timed_out: bool = Field(
        default=False,
        description="True if the bouncer's 200ms total budget was exceeded.",
    )

    @field_validator("reason")
    @classmethod
    def _no_pii_in_reason(cls, v: str) -> str:
        """Hard-coded sanity check: reason is a code, not a message echo.

        Catches the easy mistake of stuffing the user's input into the reason
        field for "debugging." If a reason ever needs to be longer than 200
        chars, the limit is wrong, not the rule.
        """
        if "\n" in v or "@" in v:
            raise ValueError("reason must be a short code, not free text or PII")
        return v


# =============================================================================
# Layer 2 — Intent classifier
# =============================================================================


class Entity(_Frozen):
    """A typed entity recognised in the user's message.

    `value` is the raw entity string for entities that flow through redacted
    (LOCATION, PERSON, etc.). For high-sensitivity types the value will be
    the redaction TOKEN, not the original string.
    """

    type: EntityType
    value: str = Field(min_length=1, max_length=500)
    start: int = Field(ge=0, description="Character offset in the redacted message.")
    end: int = Field(ge=0)

    @field_validator("end")
    @classmethod
    def _end_after_start(cls, v: int, info: Any) -> int:
        start = info.data.get("start", 0)
        if v <= start:
            raise ValueError("end must be greater than start")
        return v


class ClassifiedIntent(_Frozen):
    """Verdict from the Intent classifier (fast or deep path)."""

    intent: str = Field(min_length=1, max_length=100)
    sub_intent: str | None = Field(default=None, max_length=100)
    domain: IntentDomain
    confidence: Confidence
    entities: tuple[Entity, ...] = Field(default_factory=tuple)
    resolved_message: str = Field(
        description=(
            "Redacted message with pronouns resolved against session history. "
            "Still redacted. Never the raw resolved message."
        ),
    )
    multi_domain: bool = Field(
        default=False,
        description="True if the message touches multiple top-level domains.",
    )
    escalate: bool = Field(
        default=False,
        description="True if confidence < 0.6 — request enters the degradation ladder.",
    )
    reasoning: str | None = Field(
        default=None,
        max_length=500,
        description="Optional short reasoning blurb. NEVER includes raw message text.",
    )
    path: ClassifierPath


# =============================================================================
# Layer 3 — Routing strategist
# =============================================================================


class RoutingContext(_Frozen):
    """Per-request context the vendor adapter uses to call Bedrock.

    Carries policy decisions and operational hints, not the message itself.
    """

    user_tier: str = Field(default="free", max_length=32)
    bedrock_region: str = Field(default="ap-southeast-1", pattern=r"^[a-z]{2}-[a-z]+-\d$")
    timeout_seconds: float = Field(gt=0, le=120, description="Per-vendor-call timeout.")
    max_retries: int = Field(ge=0, le=5)
    streaming: bool = Field(default=True)


class RoutingPlan(_Frozen):
    """Verdict from the Routing strategist."""

    primary_vendor: str = Field(min_length=1, max_length=100)
    fallback_chain: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Ordered fallback vendors. Empty tuple means no fallback.",
    )
    context: RoutingContext
    applied_policies: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Policy IDs applied (e.g. 'sg_residency', 'mas_block').",
    )
    policy_modified: bool = Field(
        default=False,
        description="True if policy engine altered the vendor choice.",
    )
    blocked: bool = Field(
        default=False,
        description="True if policy engine blocked the request entirely.",
    )
    path: StrategistPath


# =============================================================================
# Redaction
# =============================================================================


class RedactionResult(_Frozen):
    """Output of the input redaction pass at orchestrator entry.

    The token vault (Redis) holds the mapping back to original entity values,
    keyed by correlation_id. The vault is never represented in this model —
    that's deliberate: nothing downstream needs the original values.
    """

    redacted_message: str = Field(min_length=1)
    entity_types_found: tuple[EntityType, ...] = Field(default_factory=tuple)
    entity_count: int = Field(ge=0)
    was_redacted: bool
    correlation_id: CorrelationID

    @field_validator("entity_count")
    @classmethod
    def _count_matches_types(cls, v: int, info: Any) -> int:
        types = info.data.get("entity_types_found", ())
        # entity_count >= len(unique types) — a type may appear multiple times
        if v < len(types):
            raise ValueError(
                f"entity_count ({v}) cannot be less than unique entity types found ({len(types)})"
            )
        return v


# =============================================================================
# Pipeline envelope
# =============================================================================


class PipelineEnvelope(_Frozen):
    """The single object that flows through the pipeline after redaction.

    Constructed once by the Orchestrator after the redaction pass. Immutable
    thereafter. If a layer needs to add metadata, it returns a sibling result
    object (BounceResult, ClassifiedIntent, RoutingPlan); it does NOT mutate
    the envelope.

    The raw user message is NEVER in this envelope — only `redacted_message`.
    For audit purposes we carry `raw_message_hash` (a one-way hash), not the
    raw text.
    """

    correlation_id: CorrelationID
    user_sub: UserSub
    session_id: str = Field(min_length=1, max_length=128)
    redacted_message: str = Field(min_length=1)
    raw_message_hash: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
        description="SHA-256 hex digest of the raw message. Used for audit only.",
    )
    entity_types_redacted: tuple[EntityType, ...] = Field(default_factory=tuple)
    entity_count: int = Field(ge=0)
    was_redacted: bool
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    bedrock_region: str = Field(default="ap-southeast-1", pattern=r"^[a-z]{2}-[a-z]+-\d$")
    source_ip: str = Field(
        min_length=7,
        max_length=45,
        description="Client IP from API Gateway. IPv4 or IPv6.",
    )

    @field_validator("timestamp")
    @classmethod
    def _timezone_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware (UTC)")
        return v


# =============================================================================
# Public API
# =============================================================================

__all__ = [
    # Models
    "BounceResult",
    # Enums
    "BouncerLayer",
    "ClassifiedIntent",
    "ClassifierPath",
    # Type aliases
    "Confidence",
    "CorrelationID",
    "Entity",
    "EntityType",
    "IntentDomain",
    "PipelineEnvelope",
    "RedactionResult",
    "RoutingContext",
    "RoutingPlan",
    "StrategistPath",
    "UserSub",
]
