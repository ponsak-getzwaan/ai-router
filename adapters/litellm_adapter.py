"""Vendor adapter: LiteLLM configured against AWS Bedrock.

All models are referenced by cross-region inference profile IDs (apac.* prefix).
Streaming is enabled by default. Non-streaming is opt-in via the plan context.

Non-negotiable: no import anthropic, no import openai.
LiteLLM calls Bedrock; Bedrock calls the vendor.
"""

from __future__ import annotations

import asyncio

import litellm

from shared.errors import BedrockError, BedrockTimeout
from shared.logging import safe_log
from shared.models import PipelineEnvelope, RoutingPlan

# LiteLLM needs AWS credentials from the environment (boto3 default chain).
# We disable its verbose logging to keep structlog the single log source.
litellm.set_verbose = False  # type: ignore[attr-defined]
litellm.drop_params = True  # ignore unknown params silently


_PREFIX_TO_REGION: dict[str, str] = {
    "apac.":   "ap-southeast-1",
    "global.": "ap-southeast-1",
    "us.":     "us-east-1",
    "eu.":     "eu-west-1",
}


def _litellm_model(inference_profile_id: str) -> str:
    """Convert a Bedrock inference profile ID to LiteLLM's bedrock/ prefix format."""
    return f"bedrock/{inference_profile_id}"


def _region_for(inference_profile_id: str) -> str:
    for prefix, region in _PREFIX_TO_REGION.items():
        if inference_profile_id.startswith(prefix):
            return region
    return "ap-southeast-1"


async def invoke(
    envelope: PipelineEnvelope,
    plan: RoutingPlan,
    system_prompt: str = "You are a helpful assistant.",
    history: list[dict[str, str]] | None = None,
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
                    history=history,
                ),
                timeout=plan.context.timeout_seconds,
            )
            safe_log.info(
                "adapters.vendor.success",
                vendor=vendor,
                was_redacted=envelope.was_redacted,
            )
            return response
        except TimeoutError:
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
    history: list[dict[str, str]] | None = None,
) -> str:
    model = _litellm_model(inference_profile_id)
    region = _region_for(inference_profile_id)
    # Build messages: system first, then last 4 history turns, then current user
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history[-4:])
    messages.append({"role": "user", "content": message})

    if streaming:
        return await _collect_stream(model, region, messages, max_retries)

    response = await litellm.acompletion(
        model=model,
        messages=messages,
        max_tokens=1024,
        num_retries=max_retries,
        aws_region_name=region,
    )
    content: str = response.choices[0].message.content or ""
    return content


async def _collect_stream(
    model: str, region: str, messages: list[dict[str, str]], max_retries: int
) -> str:
    chunks: list[str] = []
    response = await litellm.acompletion(
        model=model,
        messages=messages,
        stream=True,
        max_tokens=1024,
        num_retries=max_retries,
        aws_region_name=region,
    )
    async for chunk in response:
        delta = chunk.choices[0].delta
        if delta and delta.content:
            chunks.append(delta.content)
    return "".join(chunks)
