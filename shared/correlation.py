"""Correlation ID propagation via ContextVar.

The correlation ID threads through every layer of the pipeline, every log
line, every queue message, and every X-Ray trace. We propagate it via a
ContextVar — never as a function argument through every layer signature.

See CLAUDE.md §3 non-negotiable #5 and §7 "Orchestrator".

Usage:

    from shared.correlation import set_correlation_id, get_correlation_id

    # At the orchestrator entry point, when a message is dequeued:
    set_correlation_id(envelope.correlation_id)

    # Anywhere downstream (log handlers, sub-coroutines, etc.):
    cid = get_correlation_id()  # raises NoCorrelationIDError if not set

The ContextVar is automatically copied into spawned `asyncio` tasks (Python
3.7+ behaviour), so layer-to-layer async calls inherit it without explicit
plumbing.
"""

from __future__ import annotations

from contextvars import ContextVar
from uuid import UUID, uuid4

_correlation_id: ContextVar[UUID | None] = ContextVar("ai_router_correlation_id", default=None)


class NoCorrelationIDError(RuntimeError):
    """Raised when code reads the correlation ID before it has been set.

    This is always a bug — every code path that runs after orchestrator entry
    has a correlation ID set. If you see this in production, something is
    bypassing the orchestrator.
    """


def set_correlation_id(cid: UUID) -> None:
    """Set the correlation ID for the current async context.

    Called by the Orchestrator at the very first action when a message is
    dequeued. Should not be called anywhere else in normal request handling.
    """
    _correlation_id.set(cid)


def get_correlation_id() -> UUID:
    """Read the correlation ID for the current async context.

    Raises:
        NoCorrelationIDError: if the correlation ID has not been set. Always
            indicates that code is running outside an orchestrator-managed
            request context.
    """
    cid = _correlation_id.get()
    if cid is None:
        raise NoCorrelationIDError(
            "correlation_id is not set in this context — "
            "did you forget to call set_correlation_id() at the orchestrator entry?"
        )
    return cid


def get_correlation_id_or_none() -> UUID | None:
    """Read the correlation ID, returning None if unset.

    Use this in places (e.g. log processors) that can run outside a request
    context and shouldn't crash when no correlation is in flight.
    """
    return _correlation_id.get()


def new_correlation_id() -> UUID:
    """Generate a fresh UUID4 to use as a correlation ID."""
    return uuid4()


__all__ = [
    "NoCorrelationIDError",
    "get_correlation_id",
    "get_correlation_id_or_none",
    "new_correlation_id",
    "set_correlation_id",
]
