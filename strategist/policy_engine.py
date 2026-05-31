"""Policy engine: runs after vendor selection.

Enforces compliance blocks. Data residency is the admin's responsibility —
the routing rule editor shows a compliance warning for us.* models, and the
admin's explicit choice is honoured here without override.
"""

from __future__ import annotations

from shared.logging import safe_log
from shared.models import ClassifiedIntent, PipelineEnvelope, RoutingPlan

# Intent categories blocked for legal/compliance reasons (MAS regulation, etc.)
_BLOCKED_INTENTS: frozenset[str] = frozenset(
    {
        "mas_regulated_advice",
        "financial_advice",
        "legal_advice",
    }
)


def apply_policies(
    plan: RoutingPlan,
    envelope: PipelineEnvelope,
    intent: ClassifiedIntent,
) -> RoutingPlan:
    """Apply all policies and return a (possibly modified) RoutingPlan.

    Policies run in order; the first blocking policy short-circuits the rest.
    Returns a new RoutingPlan (envelope is immutable).
    """
    applied: list[str] = []
    blocked = False
    primary_vendor = plan.primary_vendor

    # Compliance blocks
    if intent.intent in _BLOCKED_INTENTS:
        safe_log.warning(
            "policy.compliance.blocked",
            intent=intent.intent,
            blocked=True,
            applied_policies=["mas_block"],
        )
        applied.append("mas_block")
        blocked = True

    policy_modified = primary_vendor != plan.primary_vendor or blocked

    return RoutingPlan(
        primary_vendor=primary_vendor,
        fallback_chain=plan.fallback_chain,
        context=plan.context,
        applied_policies=tuple(applied),
        policy_modified=policy_modified,
        blocked=blocked,
        path=plan.path,
    )
