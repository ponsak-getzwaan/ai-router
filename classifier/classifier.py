"""Intent classifier: fast path first, deep path if fast path misses."""

from __future__ import annotations

from classifier.config import ClassifierConfig
from classifier.deep_path import DeepPathClassifier
from classifier.fast_path import classify_fast, is_followup
from shared.bedrock import BedrockRuntime
from shared.logging import safe_log
from shared.models import ClassifiedIntent, PipelineEnvelope


class Classifier:
    def __init__(self, config: ClassifierConfig, bedrock: BedrockRuntime) -> None:
        self._config = config
        self._deep = DeepPathClassifier(config, bedrock)

    async def classify(
        self,
        envelope: PipelineEnvelope,
        history: list[dict[str, str]] | None = None,
    ) -> ClassifiedIntent:
        # Skip fast path when we have history context and the message looks like
        # a follow-up — keyword rules can't account for prior conversation turns.
        if history and is_followup(envelope.redacted_message):
            safe_log.info("classifier.followup_detected")
        else:
            # Fast path — keyword heuristics, no LLM
            fast_result = classify_fast(
                envelope.redacted_message, self._config.fast_path_threshold
            )
            if fast_result is not None:
                safe_log.info(
                    "classifier.fast_path.hit",
                    intent=fast_result.intent,
                    confidence=fast_result.confidence,
                    path=fast_result.path,
                )
                return fast_result

        # Deep path — Sonnet, optionally with prior history for context
        safe_log.info("classifier.deep_path.triggered")
        return await self._deep.classify(envelope, history=history)


__all__ = ["Classifier"]
