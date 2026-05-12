"""Unit tests for redactor.streaming_redactor.StreamingRedactor.

Uses fakeredis for an in-process async Redis implementation.
asyncio_mode = "auto" — no @pytest.mark.asyncio needed.
"""

from __future__ import annotations

from uuid import uuid4

import fakeredis.aioredis as fakeredis
import pytest

from redactor.streaming_redactor import BUFFER_SIZE, SAFETY_MARGIN, StreamingRedactor
from redactor.vault import TokenVault


@pytest.fixture
async def redis():  # type: ignore[misc]
    r = fakeredis.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
async def vault(redis):  # type: ignore[misc]
    return TokenVault(redis, ttl_seconds=300)


async def test_small_chunk_below_buffer_emits_nothing(vault: TokenVault) -> None:
    cid = uuid4()
    sr = StreamingRedactor(vault, cid)

    # Feed a chunk shorter than BUFFER_SIZE
    short_chunk = "A" * (BUFFER_SIZE - 1)
    output = await sr.feed(short_chunk)
    assert output == ""


async def test_large_chunk_emits_partial_output(vault: TokenVault) -> None:
    cid = uuid4()
    sr = StreamingRedactor(vault, cid)

    # Feed a chunk larger than BUFFER_SIZE
    chunk = "B" * (BUFFER_SIZE + 10)
    output = await sr.feed(chunk)

    # Should have emitted something
    assert len(output) > 0
    # The emitted portion should not include the last SAFETY_MARGIN chars
    # (those are retained in the buffer)
    assert len(output) == len(chunk) - SAFETY_MARGIN


async def test_flush_emits_remaining_buffer(vault: TokenVault) -> None:
    cid = uuid4()
    sr = StreamingRedactor(vault, cid)

    # Feed a small chunk (won't trigger emit)
    await sr.feed("Hello world. ")
    flushed = await sr.flush()

    assert flushed == "Hello world. "


async def test_token_spanning_chunk_boundary_restored_correctly(vault: TokenVault) -> None:
    """A VAULT_ token split across the safety margin boundary must be restored on flush."""
    cid = uuid4()
    token = "VAULT_AABBCCDDEEFF"
    await vault.store(cid, {token: "S1234567A"})

    sr = StreamingRedactor(vault, cid)

    # Build content so the token appears right at the boundary area.
    # Put padding before so buffer_size is reached, then the token.
    # We want the token to land in the SAFETY_MARGIN (kept in buffer).
    padding = "X" * (BUFFER_SIZE - SAFETY_MARGIN - 5)
    content = padding + token  # total < BUFFER_SIZE, so no emit yet

    output = await sr.feed(content)
    # Nothing emitted yet (content < BUFFER_SIZE)
    assert output == "" or "S1234567A" not in output

    flushed = await sr.flush()
    # After flush the token should be restored
    assert "S1234567A" in flushed


async def test_multiple_feeds_then_flush(vault: TokenVault) -> None:
    cid = uuid4()
    sr = StreamingRedactor(vault, cid)

    parts = ["Hello ", "world ", "this ", "is ", "a ", "test."]
    outputs = []
    for part in parts:
        out = await sr.feed(part)
        outputs.append(out)

    flushed = await sr.flush()
    combined = "".join(outputs) + flushed
    assert combined == "Hello world this is a test."


async def test_token_in_flush_is_restored(vault: TokenVault) -> None:
    cid = uuid4()
    token = "VAULT_AABBCCDDEEFF"
    await vault.store(cid, {token: "S1234567A"})

    sr = StreamingRedactor(vault, cid)
    # Token only appears in the final buffer, never triggers buffer emit
    await sr.feed(f"NRIC is {token}.")

    flushed = await sr.flush()
    assert "S1234567A" in flushed
    assert token not in flushed


async def test_buffer_constants_are_correct() -> None:
    assert BUFFER_SIZE == 200
    assert SAFETY_MARGIN == 50
