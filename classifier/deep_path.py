"""Deep-path intent classifier using Claude Sonnet via Bedrock.

Called when the fast path does not produce a confident match.
Sonnet returns structured JSON with intent, confidence, and reasoning.

MCP tools (taxonomy, session history, guardrails, entity context) are
Phase 2 — stubs here emit warnings so they're easy to find and upgrade.
"""

from __future__ import annotations

import json
from typing import Any

from classifier.config import ClassifierConfig
from shared.bedrock import BedrockRuntime
from shared.errors import BedrockError
from shared.logging import safe_log
from shared.models import ClassifiedIntent, ClassifierPath, IntentDomain, PipelineEnvelope

_SYSTEM_PROMPT = """You are an intent classifier for a customer service AI router.

IMPORTANT: Messages may contain tokens like VAULT_XXXXXXXXXX. These are redacted PII \
values (e.g. NRIC, credit card numbers, passport numbers). Treat them as stand-ins for \
sensitive personal data and classify the message based on the surrounding context and intent.

When the conversation includes prior turns, use them to resolve pronouns and references \
(e.g. "it", "this", "that", "they") in the CURRENT user message before classifying. \
Classify only the intent of the LAST user message — not the conversation as a whole.

Classify the current user message into one of these intents:
- general_qa: general questions, explanations, summaries, comparisons
- code_assistance: coding, debugging, programming help
- simple_transactional: quick lookups, prices, hours, contacts
- out_of_scope: requests the system cannot handle
- ambiguous: unclear intent even after considering prior context

Reply with JSON only:
{
  "intent": "<intent>",
  "domain": "<intent>",
  "confidence": 0.0-1.0,
  "reasoning": "<one sentence, no user content>",
  "escalate": true|false
}
Set escalate=true if confidence < 0.6 or intent is out_of_scope/ambiguous."""

_DOMAIN_MAP: dict[str, IntentDomain] = {
    "general_qa": IntentDomain.GENERAL_QA,
    "code_assistance": IntentDomain.CODE_ASSISTANCE,
    "simple_transactional": IntentDomain.SIMPLE_TRANSACTIONAL,
    "out_of_scope": IntentDomain.OUT_OF_SCOPE,
    "ambiguous": IntentDomain.AMBIGUOUS,
}


class DeepPathClassifier:
    def __init__(self, config: ClassifierConfig, bedrock: BedrockRuntime) -> None:
        self._config = config
        self._bedrock = bedrock

    async def classify(
        self,
        envelope: PipelineEnvelope,
        history: list[dict[str, str]] | None = None,
    ) -> ClassifiedIntent:
        """Call Sonnet and parse the classification result.

        On Bedrock error, returns an ambiguous/escalate result (fail-safe,
        not fail-open — unlike the Bouncer, the classifier CAN escalate).
        """
        # Prepend up to the last 4 turns (2 exchanges) for follow-up context.
        prior: list[dict[str, Any]] = list(history[-4:]) if history else []
        body: dict[str, Any] = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": self._config.sonnet_max_tokens,
            "system": _SYSTEM_PROMPT,
            "messages": prior + [{"role": "user", "content": envelope.redacted_message}],
        }

        try:
            response = await self._bedrock.invoke_model(self._config.sonnet_model_id, body)
            text: str = response["content"][0]["text"]
            parsed: dict[str, Any] = json.loads(text)

            intent_str: str = str(parsed.get("intent", "ambiguous"))
            domain = _DOMAIN_MAP.get(intent_str, IntentDomain.AMBIGUOUS)
            confidence: float = max(0.0, min(1.0, float(parsed.get("confidence", 0.0))))
            raw_reasoning: str = str(parsed.get("reasoning", ""))[:500]
            escalate: bool = bool(
                parsed.get("escalate", confidence < self._config.escalate_threshold)
            )

            safe_log.info(
                "classifier.deep_path.verdict",
                intent=intent_str,
                domain=domain,
                confidence=confidence,
                escalate=escalate,
            )

            return ClassifiedIntent(
                intent=intent_str,
                domain=domain,
                confidence=confidence,
                resolved_message=envelope.redacted_message,
                reasoning=raw_reasoning or None,
                escalate=escalate or confidence < self._config.escalate_threshold,
                path=ClassifierPath.DEEP,
            )

        except (BedrockError, KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
            safe_log.warning(
                "classifier.deep_path.error", error_type=type(exc).__name__, escalate=True
            )
            return ClassifiedIntent(
                intent="ambiguous",
                domain=IntentDomain.AMBIGUOUS,
                confidence=0.0,
                resolved_message=envelope.redacted_message,
                escalate=True,
                path=ClassifierPath.DEEP,
            )
