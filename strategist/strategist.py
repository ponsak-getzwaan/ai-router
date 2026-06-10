"""Routing strategist: selects vendor, applies policies, builds RoutingPlan."""

from __future__ import annotations

import aioboto3  # type: ignore[import-untyped]

from shared.bedrock import BedrockRuntime
from shared.logging import safe_log
from shared.models import (
    ClassifiedIntent,
    PipelineEnvelope,
    RoutingContext,
    RoutingPlan,
)
from strategist.config import StrategistConfig
from strategist.policy_engine import apply_policies
from strategist.vendor_selector import VendorSelector

_HAIKU_ID = "apac.anthropic.claude-3-haiku-20240307-v1:0"
_SONNET_ID = "apac.anthropic.claude-3-5-sonnet-20241022-v2:0"


class Strategist:
    def __init__(self, config: StrategistConfig, bedrock: BedrockRuntime) -> None:
        self._config = config
        self._session: aioboto3.Session = aioboto3.Session()
        self._selector = VendorSelector(config, bedrock, self._session)

    async def route(
        self, envelope: PipelineEnvelope, intent: ClassifiedIntent
    ) -> RoutingPlan:
        vendor, path = await self._selector.select(intent)

        # Escalate sentinel — routing rule says "send to human review"
        if vendor == "escalate":
            safe_log.info("strategist.plan", primary_vendor="escalate", path=path,
                          blocked=False, policy_modified=False, applied_policies=())
            return RoutingPlan(
                primary_vendor="escalate",
                fallback_chain=(),
                context=RoutingContext(
                    bedrock_region=self._config.bedrock_region,
                    timeout_seconds=self._config.sonnet_timeout_s,
                    max_retries=0,
                    streaming=False,
                ),
                path=path,
            )

        # Build timeout/context based on the selected vendor
        is_haiku = _HAIKU_ID in vendor
        timeout_s = self._config.haiku_timeout_s if is_haiku else self._config.sonnet_timeout_s
        fallback = (_HAIKU_ID,) if not is_haiku else ()

        plan = RoutingPlan(
            primary_vendor=vendor,
            fallback_chain=fallback,
            context=RoutingContext(
                bedrock_region=self._config.bedrock_region,
                timeout_seconds=timeout_s,
                max_retries=2,
                streaming=True,
            ),
            path=path,
        )

        # Policy engine runs after vendor selection (CLAUDE.md §7 Strategist)
        final_plan = apply_policies(plan, envelope, intent)

        safe_log.info(
            "strategist.plan",
            primary_vendor=final_plan.primary_vendor,
            path=final_plan.path,
            blocked=final_plan.blocked,
            policy_modified=final_plan.policy_modified,
            applied_policies=final_plan.applied_policies,
        )

        return final_plan


__all__ = ["Strategist"]
