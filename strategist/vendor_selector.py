"""Vendor selector: three-path routing logic.

Paths (CLAUDE.md §7 Strategist):
  >= 0.85 confidence → deterministic rule lookup (no LLM)
  0.5 - 0.85         → Haiku arbitration (max 80 tokens)
  < 0.5              → escalate to human review
"""

from __future__ import annotations

import json
from typing import Any

import aioboto3  # type: ignore[import-untyped]

from shared.bedrock import BedrockRuntime
from shared.errors import BedrockError
from shared.logging import safe_log
from shared.models import ClassifiedIntent, StrategistPath

_HAIKU_SYSTEM = (
    "You confirm or correct an intent classification for a user message. "
    "Valid intents: code_assistance, general_qa, simple_transactional, out_of_scope, ambiguous. "
    'Reply with JSON only: {"intent": "<intent_name>", "reasoning": "<short_code>"}'
)

_INTENT_TO_VENDOR: dict[str, str] = {
    "code_assistance": "apac.anthropic.claude-3-5-sonnet-20241022-v2:0",
    "general_qa": "apac.anthropic.claude-3-5-sonnet-20241022-v2:0",
    "simple_transactional": "apac.anthropic.claude-3-haiku-20240307-v1:0",
}


class VendorSelector:
    def __init__(
        self,
        config: Any,  # StrategistConfig — avoid circular import
        bedrock: BedrockRuntime,
        dynamo_session: aioboto3.Session,
    ) -> None:
        self._config = config
        self._bedrock = bedrock
        self._dynamo_session = dynamo_session

    async def select(self, intent: ClassifiedIntent) -> tuple[str, StrategistPath]:
        """Return (vendor_inference_profile_id, path_used)."""
        confidence = intent.confidence

        if confidence >= self._config.deterministic_threshold:
            vendor = await self._deterministic(intent.intent)
            return vendor, StrategistPath.DETERMINISTIC

        if confidence < self._config.escalate_threshold:
            safe_log.info("strategist.escalating", confidence=confidence, escalate=True)
            return self._config.default_vendor, StrategistPath.ESCALATED

        # Haiku arbitration
        vendor = await self._haiku_arbitrate(intent)
        return vendor, StrategistPath.HAIKU_ARBITRATION

    async def _deterministic(self, intent: str) -> str:
        """Look up vendor from DynamoDB routing rules; fall back to config map."""
        try:
            async with self._dynamo_session.resource(
                "dynamodb", region_name=self._config.bedrock_region
            ) as dynamo:
                table = await dynamo.Table(self._config.dynamodb_routing_table)
                response = await table.get_item(Key={"intent": intent})
                item = response.get("Item")
                if item and "vendor" in item:
                    vendor: str = str(item["vendor"])
                    safe_log.info(
                        "strategist.deterministic.dynamo_hit",
                        intent=intent,
                        vendor=vendor,
                    )
                    return vendor
        except Exception as exc:
            safe_log.warning("strategist.dynamo.error", error_type=type(exc).__name__)

        # Fall back to in-process map, then config default
        vendor = _INTENT_TO_VENDOR.get(intent, self._config.default_vendor)
        safe_log.info("strategist.deterministic.local_map", intent=intent, vendor=vendor)
        return vendor

    async def _haiku_arbitrate(self, intent: ClassifiedIntent) -> str:
        """Use Haiku to confirm/refine the intent, then look up vendor from routing rules.

        Haiku never picks the vendor directly — that always comes from DynamoDB so that
        admin-configured routing rules are respected regardless of confidence level.
        """
        body: dict[str, Any] = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": self._config.haiku_max_tokens,
            "system": _HAIKU_SYSTEM,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"Intent: {intent.intent}, domain: {intent.domain}, "
                        f"confidence: {intent.confidence:.2f}"
                    ),
                }
            ],
        }
        refined_intent = intent.intent
        try:
            response = await self._bedrock.invoke_model(self._config.haiku_model_id, body)
            text: str = response["content"][0]["text"]
            parsed: dict[str, Any] = json.loads(text)
            refined_intent = str(parsed.get("intent", intent.intent))
            safe_log.info("strategist.haiku.verdict", refined_intent=refined_intent)
        except (BedrockError, KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
            safe_log.warning("strategist.haiku.error", error_type=type(exc).__name__)

        return await self._deterministic(refined_intent)
