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

# Approved vendor prefix: apac.* inference profiles are Singapore-resident.
_APAC_PREFIX = "apac."

# Global profiles explicitly approved despite routing outside ap-southeast-1.
# Each entry requires a deliberate product-owner decision (data-residency trade-off).
_APPROVED_GLOBAL_VENDORS: frozenset[str] = frozenset(
    {"global.anthropic.claude-sonnet-4-6"}
)

# Fallback for all other non-resident vendors.
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

    # Data residency — reroute vendors that are neither APAC-resident nor explicitly approved
    if not primary_vendor.startswith(_APAC_PREFIX) and primary_vendor not in _APPROVED_GLOBAL_VENDORS:
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
