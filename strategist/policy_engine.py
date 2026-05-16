"""Policy engine: runs after vendor selection.

Enforces data residency and compliance blocks.
Non-negotiable: selecting a non-ap-southeast-1 vendor for an SG user
must be blocked here (CLAUDE.md §7 Strategist).
"""

from __future__ import annotations

from shared.logging import safe_log
from shared.models import ClassifiedIntent, PipelineEnvelope, RoutingPlan

# Vendors that are approved for ap-southeast-1 data residency.
# All are Bedrock inference profiles — non-Bedrock vendors are always blocked.
_APPROVED_VENDORS: frozenset[str] = frozenset(
    {
        "apac.anthropic.claude-3-haiku-20240307-v1:0",
        "apac.anthropic.claude-3-5-sonnet-20241022-v2:0",
    }
)

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

    # 1. Data residency — vendor must be an approved APAC Bedrock profile
    if primary_vendor not in _APPROVED_VENDORS:
        safe_log.warning(
            "policy.residency.blocked",
            vendor=primary_vendor,
            blocked=True,
            applied_policies=["sg_residency"],
        )
        primary_vendor = "apac.anthropic.claude-3-5-sonnet-20241022-v2:0"
        applied.append("sg_residency")
        blocked = False  # rerouted, not hard-blocked

    # 2. Compliance blocks
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
