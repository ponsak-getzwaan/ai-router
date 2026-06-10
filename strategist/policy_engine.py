"""Policy engine: runs after vendor selection.

Enforces data residency and compliance blocks in that order.
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

# Approved inference profile prefixes.
# apac.*   — Singapore-resident profiles
# global.* — global cross-region profiles (compute may route outside ap-southeast-1)
# us.*     — US East profiles (required to support Meta, Mistral, and other vendors
#            that have no APAC inference profiles)
_APPROVED_PREFIXES: frozenset[str] = frozenset({"apac.", "global.", "us."})

# Fallback for unrecognised vendor strings (typos, stale config, etc.).
_SG_FALLBACK_VENDOR = "apac.anthropic.claude-3-5-sonnet-20241022-v2:0"


def apply_policies(
    plan: RoutingPlan,
    envelope: PipelineEnvelope,
    intent: ClassifiedIntent,
) -> RoutingPlan:
    """Apply all policies and return a (possibly modified) RoutingPlan.

    Policies run in order; blocking policies short-circuit the rest only for
    the blocked flag — residency rerouting still runs before compliance checks.
    Returns a new RoutingPlan (envelope is immutable).
    """
    applied: list[str] = []
    blocked = False
    primary_vendor = plan.primary_vendor

    # Escalate sentinel passes through unchanged — no residency check needed
    if primary_vendor == "escalate":
        return plan

    # Reroute vendors that don't match any approved inference profile prefix
    if not any(primary_vendor.startswith(p) for p in _APPROVED_PREFIXES):
        safe_log.warning(
            "policy.sg_residency.rerouted",
            original_vendor=primary_vendor,
            rerouted_to=_SG_FALLBACK_VENDOR,
        )
        primary_vendor = _SG_FALLBACK_VENDOR
        applied.append("sg_residency")

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
