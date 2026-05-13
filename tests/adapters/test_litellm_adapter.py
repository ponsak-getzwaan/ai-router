"""Unit tests for adapters.litellm_adapter.

All calls to litellm.acompletion are mocked — no real AWS/Bedrock calls.
asyncio_mode=auto means no @pytest.mark.asyncio needed.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from adapters.litellm_adapter import _litellm_model, invoke
from shared.errors import BedrockError, BedrockTimeout
from shared.models import (
    PipelineEnvelope,
    RoutingContext,
    RoutingPlan,
    StrategistPath,
)


# =============================================================================
# Helpers
# =============================================================================


def make_envelope(
    message: str = "Hello, can you help me?",
    user_sub: str = "user-abc-123",
) -> PipelineEnvelope:
    raw_hash = hashlib.sha256(message.encode()).hexdigest()
    return PipelineEnvelope(
        correlation_id=uuid4(),
        user_sub=user_sub,
        session_id="session-abc-123",
        redacted_message=message,
        raw_message_hash=raw_hash,
        entity_types_redacted=(),
        entity_count=0,
        was_redacted=False,
        timestamp=datetime.now(UTC),
        bedrock_region="ap-southeast-1",
        source_ip="1.2.3.4",
    )


def make_plan(
    primary_vendor: str = "apac.anthropic.claude-sonnet-4-6-20241022-v2:0",
    fallback: tuple[str, ...] = (),
    streaming: bool = False,
    timeout: float = 5.0,
) -> RoutingPlan:
    return RoutingPlan(
        primary_vendor=primary_vendor,
        fallback_chain=fallback,
        context=RoutingContext(timeout_seconds=timeout, max_retries=2, streaming=streaming),
        path=StrategistPath.DETERMINISTIC,
    )


def make_non_streaming_response(content: str = "Hello there") -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = content
    return mock_resp


class FakeStream:
    """Async iterator yielding a fixed sequence of chunks."""

    def __init__(self, contents: list[str]) -> None:
        self._contents = iter(contents)

    def __aiter__(self) -> "FakeStream":
        return self

    async def __anext__(self) -> MagicMock:
        try:
            text = next(self._contents)
        except StopIteration:
            raise StopAsyncIteration
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta = MagicMock()
        chunk.choices[0].delta.content = text
        return chunk


# =============================================================================
# Tests — _litellm_model
# =============================================================================


def test_litellm_model_prefixes_bedrock() -> None:
    result = _litellm_model("apac.foo")
    assert result == "bedrock/apac.foo"


def test_litellm_model_full_profile_id() -> None:
    pid = "apac.anthropic.claude-sonnet-4-6-20241022-v2:0"
    assert _litellm_model(pid) == f"bedrock/{pid}"


# =============================================================================
# Tests — non-streaming invoke
# =============================================================================


async def test_invoke_non_streaming_returns_text() -> None:
    envelope = make_envelope()
    plan = make_plan(streaming=False)
    mock_resp = make_non_streaming_response("Hello there")

    with patch(
        "adapters.litellm_adapter.litellm.acompletion",
        new_callable=AsyncMock,
        return_value=mock_resp,
    ):
        result = await invoke(envelope, plan)

    assert result == "Hello there"


async def test_invoke_passes_redacted_message() -> None:
    envelope = make_envelope(message="My redacted text VAULT_TOKEN_XYZ")
    plan = make_plan(streaming=False)
    mock_resp = make_non_streaming_response("ok")

    with patch(
        "adapters.litellm_adapter.litellm.acompletion",
        new_callable=AsyncMock,
        return_value=mock_resp,
    ) as mock_ac:
        await invoke(envelope, plan)

    call_kwargs = mock_ac.call_args
    messages = call_kwargs.kwargs.get("messages") or call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs["messages"]
    # messages is passed as kwarg
    messages = mock_ac.call_args.kwargs["messages"]
    user_msg = next(m for m in messages if m["role"] == "user")
    assert user_msg["content"] == "My redacted text VAULT_TOKEN_XYZ"


async def test_invoke_passes_system_prompt() -> None:
    envelope = make_envelope()
    plan = make_plan(streaming=False)
    mock_resp = make_non_streaming_response("ok")
    system_prompt = "You are a specialist assistant."

    with patch(
        "adapters.litellm_adapter.litellm.acompletion",
        new_callable=AsyncMock,
        return_value=mock_resp,
    ) as mock_ac:
        await invoke(envelope, plan, system_prompt=system_prompt)

    messages = mock_ac.call_args.kwargs["messages"]
    sys_msg = next(m for m in messages if m["role"] == "system")
    assert sys_msg["content"] == system_prompt


# =============================================================================
# Tests — streaming invoke
# =============================================================================


async def test_invoke_streaming_collects_chunks() -> None:
    envelope = make_envelope()
    plan = make_plan(streaming=True)
    stream = FakeStream(["Hello", " there", "!"])

    with patch(
        "adapters.litellm_adapter.litellm.acompletion",
        new_callable=AsyncMock,
        return_value=stream,
    ):
        result = await invoke(envelope, plan)

    assert result == "Hello there!"


# =============================================================================
# Tests — fallback behaviour
# =============================================================================


async def test_invoke_falls_back_on_timeout() -> None:
    """Primary times out (asyncio.TimeoutError), fallback succeeds."""
    envelope = make_envelope()
    plan = make_plan(
        primary_vendor="apac.primary",
        fallback=("apac.fallback",),
        streaming=False,
    )
    mock_resp = make_non_streaming_response("fallback response")

    call_count = 0

    async def side_effect(**kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise asyncio.TimeoutError()
        return mock_resp

    with patch(
        "adapters.litellm_adapter.litellm.acompletion",
        side_effect=side_effect,
    ):
        result = await invoke(envelope, plan)

    assert result == "fallback response"


async def test_invoke_falls_back_on_exception() -> None:
    """Primary raises generic Exception, fallback succeeds."""
    envelope = make_envelope()
    plan = make_plan(
        primary_vendor="apac.primary",
        fallback=("apac.fallback",),
        streaming=False,
    )
    mock_resp = make_non_streaming_response("fallback ok")

    call_count = 0

    async def side_effect(**kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("connection refused")
        return mock_resp

    with patch(
        "adapters.litellm_adapter.litellm.acompletion",
        side_effect=side_effect,
    ):
        result = await invoke(envelope, plan)

    assert result == "fallback ok"


async def test_invoke_raises_bedrock_error_when_all_fail() -> None:
    """Both primary and fallback raise — should get BedrockError."""
    envelope = make_envelope()
    plan = make_plan(
        primary_vendor="apac.primary",
        fallback=("apac.fallback",),
        streaming=False,
    )

    with patch(
        "adapters.litellm_adapter.litellm.acompletion",
        side_effect=RuntimeError("unavailable"),
    ):
        with pytest.raises(BedrockError):
            await invoke(envelope, plan)


async def test_invoke_raises_bedrock_timeout_when_timeout() -> None:
    """Primary times out, no fallback — should get BedrockTimeout."""
    envelope = make_envelope()
    plan = make_plan(primary_vendor="apac.primary", fallback=(), streaming=False)

    with patch(
        "adapters.litellm_adapter.litellm.acompletion",
        side_effect=asyncio.TimeoutError(),
    ):
        with pytest.raises(BedrockTimeout):
            await invoke(envelope, plan)


# =============================================================================
# Tests — asyncio.wait_for integration
# =============================================================================


async def test_invoke_uses_plan_timeout() -> None:
    """asyncio.wait_for should be called with plan.context.timeout_seconds."""
    envelope = make_envelope()
    plan = make_plan(streaming=False, timeout=7.5)
    mock_resp = make_non_streaming_response("ok")

    captured_timeouts: list[float] = []
    original_wait_for = asyncio.wait_for

    async def capturing_wait_for(coro: object, timeout: float) -> object:  # type: ignore[return]
        captured_timeouts.append(timeout)
        return await original_wait_for(coro, timeout)  # type: ignore[arg-type]

    with patch(
        "adapters.litellm_adapter.litellm.acompletion",
        new_callable=AsyncMock,
        return_value=mock_resp,
    ):
        with patch("adapters.litellm_adapter.asyncio.wait_for", side_effect=capturing_wait_for):
            await invoke(envelope, plan)

    assert captured_timeouts == [7.5]
