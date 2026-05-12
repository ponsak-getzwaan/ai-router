"""Unit tests for redactor.vault.TokenVault.

Uses fakeredis for an in-process async Redis implementation.
asyncio_mode = "auto" (set in pyproject.toml) — no @pytest.mark.asyncio needed.
"""

from __future__ import annotations

from uuid import uuid4

import fakeredis.aioredis as fakeredis
import pytest

from redactor.vault import TokenVault


@pytest.fixture
async def redis():  # type: ignore[misc]
    r = fakeredis.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
async def vault(redis):  # type: ignore[misc]
    return TokenVault(redis, ttl_seconds=300)


async def test_store_and_restore_single_token(vault: TokenVault) -> None:
    cid = uuid4()
    token_map = {"VAULT_AABBCCDDEEFF": "S1234567A"}
    await vault.store(cid, token_map)

    result = await vault.restore(cid, "The NRIC is VAULT_AABBCCDDEEFF in text.")
    assert result == "The NRIC is S1234567A in text."


async def test_restore_multiple_tokens_in_one_text(vault: TokenVault) -> None:
    cid = uuid4()
    token_map = {
        "VAULT_111111111111": "S1234567A",
        "VAULT_222222222222": "F9876543Z",
    }
    await vault.store(cid, token_map)

    text = "NRIC VAULT_111111111111 and FIN VAULT_222222222222"
    result = await vault.restore(cid, text)
    assert result == "NRIC S1234567A and FIN F9876543Z"


async def test_restore_unknown_token_left_unchanged(vault: TokenVault) -> None:
    cid = uuid4()
    # Store nothing — the token is not in the vault
    result = await vault.restore(cid, "Missing VAULT_DEADBEEF1234 here.")
    assert result == "Missing VAULT_DEADBEEF1234 here."


async def test_delete_all_removes_keys(redis, vault: TokenVault) -> None:
    cid = uuid4()
    token_map = {
        "VAULT_AABBCCDDEEFF": "original1",
        "VAULT_112233445566": "original2",
    }
    await vault.store(cid, token_map)

    count = await vault.delete_all(cid)
    assert count == 2

    # Keys should no longer exist
    for token in token_map:
        key = f"vault:{cid}:{token}"
        exists = await redis.exists(key)
        assert exists == 0


async def test_delete_all_empty_returns_zero(vault: TokenVault) -> None:
    cid = uuid4()
    count = await vault.delete_all(cid)
    assert count == 0


async def test_store_uses_correct_key_format(redis, vault: TokenVault) -> None:
    cid = uuid4()
    token = "VAULT_AABBCCDDEEFF"
    original = "S1234567A"
    await vault.store(cid, {token: original})

    key = f"vault:{cid}:{token}"
    value = await redis.get(key)
    assert value is not None
    assert value.decode() == original


async def test_restore_no_tokens_returns_text_unchanged(vault: TokenVault) -> None:
    cid = uuid4()
    text = "Hello, this is plain text with no vault tokens."
    result = await vault.restore(cid, text)
    assert result == text


async def test_store_sets_ttl(redis, vault: TokenVault) -> None:
    cid = uuid4()
    token = "VAULT_AABBCCDDEEFF"
    await vault.store(cid, {token: "value"})

    key = f"vault:{cid}:{token}"
    ttl_ms = await redis.pttl(key)
    # TTL should be set (positive) and close to 300 seconds
    assert ttl_ms > 0, "Expected a TTL to be set on the vault key"
    assert ttl_ms <= 300_000


async def test_restore_handles_expired_token(vault: TokenVault) -> None:
    """A token whose key has expired (not in vault) stays as VAULT_ in output."""
    cid = uuid4()
    # We never store this token — simulates expiry
    text = "Value was VAULT_EXPIREDTOKEN1 before."
    result = await vault.restore(cid, text)
    # Token not in vault → left as-is
    assert "VAULT_EXPIREDTOKEN1" in result
