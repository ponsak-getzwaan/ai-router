"""Allowlist-based structured logging.

The non-negotiable: PII never appears in logs. The natural code people write
(`logger.exception(e)`, `logger.info(f"got message: {msg}")`) leaks. The
mechanism we use to prevent this is an explicit field allowlist — anything
not on the list is dropped at the log processor level, even if a developer
accidentally passes it.

Usage:

    from shared.logging import safe_log

    safe_log.info(
        "bouncer.rule_gate.passed",
        user_sub=user_sub,           # allowlisted
        rule_gate_latency_ms=4.2,    # allowlisted
        raw_message=user_input,      # NOT allowlisted → dropped silently
    )

To add a new field to the allowlist, edit `_ALLOWED_FIELDS` below AND justify
it in the PR description. Don't add fields that could carry user-supplied
content — that's the whole point of the allowlist.

Errors are logged as type names, not messages:

    try:
        await call_bedrock()
    except BedrockTimeout as e:
        safe_log.warning("bouncer.haiku.timeout", error_type=type(e).__name__)
        # NOT: error_message=str(e) — may contain echoed user input

See CLAUDE.md §5 and §3 non-negotiable #6.
"""

from __future__ import annotations

import logging
from typing import Any

import structlog

from shared.correlation import get_correlation_id_or_none

# =============================================================================
# Field allowlist — the security boundary
# =============================================================================
#
# Add to this list ONLY in a PR that justifies the addition. Fields here are
# trusted to never carry PII or user-supplied content.
#
# DO NOT add: message, body, content, prompt, text, email, phone, name,
# address, response, output, input, query, question, answer, error_message.
# =============================================================================

_ALLOWED_FIELDS: frozenset[str] = frozenset(
    {
        # Identity
        "correlation_id",
        "user_sub",
        "session_id",
        "request_id",
        # Pipeline metadata
        "layer",
        "path",
        "vendor",
        "intent",
        "sub_intent",
        "domain",
        "primary_vendor",
        "fallback_chain",
        "applied_policies",
        # Outcomes
        "allowed",
        "escalate",
        "blocked",
        "policy_modified",
        "was_redacted",
        "timed_out",
        "multi_domain",
        # Numeric
        "confidence",
        "entity_count",
        "rule_gate_latency_ms",
        "haiku_latency_ms",
        "fast_path_latency_ms",
        "deep_path_latency_ms",
        "vendor_latency_ms",
        "redaction_latency_ms",
        "total_latency_ms",
        "retry_count",
        "tokens_in",
        "tokens_out",
        # Errors (type names only)
        "error_type",
        "exit_code",
        "http_status",
        # Region / infrastructure
        "bedrock_region",
        "service_name",
        "service_version",
        # Entity types (the type names, NEVER the values)
        "entity_types",
        "entity_types_redacted",
        "entity_types_found",
        # Reason codes (short strings, validated by Pydantic to not be PII)
        "reason",
    }
)


# =============================================================================
# Processors
# =============================================================================


def _strip_disallowed_fields(
    _logger: Any, _method_name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    """Drop any field not on the allowlist.

    The event field itself (the message) is preserved by structlog convention
    and is the responsibility of the caller — it should be a short event code
    like 'bouncer.rule_gate.passed', not free text.
    """
    return {
        k: v
        for k, v in event_dict.items()
        if k in _ALLOWED_FIELDS or k in {"event", "level", "timestamp", "logger"}
    }


def _inject_correlation_id(
    _logger: Any, _method_name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    """Inject the correlation ID from the ContextVar if available."""
    cid = get_correlation_id_or_none()
    if cid is not None:
        event_dict["correlation_id"] = str(cid)
    return event_dict


def configure(*, level: int = logging.INFO, json_output: bool = True) -> None:
    """Configure structlog for the process.

    Call once at process startup (orchestrator main, sidecar main, etc.).
    Idempotent.
    """
    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        _inject_correlation_id,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _strip_disallowed_fields,  # always last before rendering
    ]
    if json_output:
        processors.append(structlog.processors.JSONRenderer())
    else:
        # Human-readable output for local dev only
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


# Module-level logger configured on import. Tests can call `configure()` again
# to override (e.g. for human-readable output).
configure()

# The singleton callers import. Use `safe_log.info(...)`, `safe_log.warning(...)`, etc.
safe_log: structlog.stdlib.BoundLogger = structlog.get_logger("ai_router")


__all__ = ["configure", "safe_log"]
