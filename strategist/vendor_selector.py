"""Vendor selector: three-path routing logic.

Paths (CLAUDE.md §7 Strategist):
  >= 0.85 confidence → deterministic rule lookup (no LLM)
  0.5 – 0.85         → Haiku arbitration (max 80 tokens)
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
    "You select the best AI vendor for a classified user intent. "
    'Reply with JSON only: {"vendor": "<inference_profile_id>", "reasoning": "<short_code>"}'
)

_INTENT_TO_VENDOR: dict[str, str] = {
    "code_assistance": "apac.anthropic.claude-sonnet-4-6-20241022-v2:0",
    "general_qa": "apac.anthropic.claude-sonnet-4-6-20241022-v2:0",
    "simple_transactional": "apac.anthropic.claude-haiku-4-5-20241022-v1:0",
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
        try:
            response = await self._bedrock.invoke_model(self._config.haiku_model_id, body)
            text: str = response["content"][0]["text"]
            parsed: dict[str, Any] = json.loads(text)
            vendor = str(parsed.get("vendor", self._config.default_vendor))
            safe_log.info("strategist.haiku.verdict", vendor=vendor)
            return vendor
        except (BedrockError, KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
            safe_log.warning("strategist.haiku.error", error_type=type(exc).__name__)
            default: str = self._config.default_vendor
            return _INTENT_TO_VENDOR.get(intent.intent, default)
