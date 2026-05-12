"""Vendor adapter: LiteLLM configured against AWS Bedrock.

All models are referenced by cross-region inference profile IDs (apac.* prefix).
Streaming is enabled by default. Non-streaming is opt-in via the plan context.

Non-negotiable: no import anthropic, no import openai.
LiteLLM calls Bedrock; Bedrock calls the vendor.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

import litellm  # type: ignore[import-untyped]

from shared.errors import BedrockError, BedrockTimeout
from shared.logging import safe_log
from shared.models import PipelineEnvelope, RoutingPlan

# LiteLLM needs AWS credentials from the environment (boto3 default chain).
# We disable its verbose logging to keep structlog the single log source.
litellm.set_verbose = False
litellm.drop_params = True  # ignore unknown params silently


def _litellm_model(inference_profile_id: str) -> str:
    """Convert a Bedrock inference profile ID to LiteLLM's bedrock/ prefix format."""
    return f"bedrock/{inference_profile_id}"


async def invoke(
    envelope: PipelineEnvelope,
    plan: RoutingPlan,
    system_prompt: str = "You are a helpful assistant.",
) -> str:
    """Call the primary vendor and return the full response text.

    Attempts the primary vendor first, then each fallback in order.
    Raises BedrockError if all vendors fail.
    """
    vendors = [plan.primary_vendor, *plan.fallback_chain]
    last_exc: Exception = BedrockError("no_vendors_tried")

    for vendor in vendors:
        try:
            response = await asyncio.wait_for(
                _call_litellm(
                    vendor,
                    envelope.redacted_message,
                    system_prompt,
                    plan.context.streaming,
                    plan.context.max_retries,
                ),
                timeout=plan.context.timeout_seconds,
            )
            safe_log.info(
                "adapters.vendor.success",
                vendor=vendor,
                was_redacted=envelope.was_redacted,
            )
            return response
        except asyncio.TimeoutError as exc:
            safe_log.warning("adapters.vendor.timeout", vendor=vendor, error_type="TimeoutError")
            last_exc = BedrockTimeout("TimeoutError")
        except Exception as exc:
            safe_log.warning("adapters.vendor.error", vendor=vendor, error_type=type(exc).__name__)
            last_exc = BedrockError(type(exc).__name__)

    raise last_exc


async def _call_litellm(
    inference_profile_id: str,
    message: str,
    system_prompt: str,
    streaming: bool,
    max_retries: int,
) -> str:
    model = _litellm_model(inference_profile_id)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": message},
    ]

    if streaming:
        return await _collect_stream(model, messages, max_retries)

    response = await litellm.acompletion(
        model=model,
        messages=messages,
        num_retries=max_retries,
    )
    content: str = response.choices[0].message.content or ""
    return content


async def _collect_stream(
    model: str, messages: list[dict[str, str]], max_retries: int
) -> str:
    chunks: list[str] = []
    response = await litellm.acompletion(
        model=model,
        messages=messages,
        stream=True,
        num_retries=max_retries,
    )
    async for chunk in response:
        delta = chunk.choices[0].delta
        if delta and delta.content:
            chunks.append(delta.content)
    return "".join(chunks)
