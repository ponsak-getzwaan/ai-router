"""Unit tests for orchestrator.vault.TokenVault.

Uses fakeredis.aioredis.FakeRedis — no real Redis connection.
asyncio_mode=auto means no @pytest.mark.asyncio needed.
"""

from __future__ import annotations

import fakeredis.aioredis  # type: ignore[import-untyped]
import pytest

from orchestrator.vault import TokenVault


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
async def redis() -> fakeredis.aioredis.FakeRedis:  # type: ignore[misc]
    r: fakeredis.aioredis.FakeRedis = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
def vault(redis: fakeredis.aioredis.FakeRedis) -> TokenVault:
    return TokenVault(redis, ttl_seconds=300)


CID = "corr-id-abc-123"


# =============================================================================
# Tests
# =============================================================================


async def test_store_and_restore_replaces_token(
    vault: TokenVault, redis: fakeredis.aioredis.FakeRedis
) -> None:
    tokens = {"VAULT_AABBCCDDEE11": "S1234567A"}
    await vault.store(CID, tokens)

    result = await vault.restore(CID, "My NRIC is VAULT_AABBCCDDEE11 thanks")
    assert "S1234567A" in result
    assert "VAULT_AABBCCDDEE11" not in result


async def test_restore_no_vault_in_text_skips_redis(
    vault: TokenVault, redis: fakeredis.aioredis.FakeRedis
) -> None:
    """Text without 'VAULT_' should be returned unchanged without touching Redis."""
    text = "Hello, how are you today?"
    result = await vault.restore(CID, text)
    assert result == text


async def test_restore_multiple_tokens(vault: TokenVault) -> None:
    tokens = {
        "VAULT_TOKEN_AAAA": "Alice",
        "VAULT_TOKEN_BBBB": "9123-4567",
    }
    await vault.store(CID, tokens)

    text = "Name: VAULT_TOKEN_AAAA, Phone: VAULT_TOKEN_BBBB"
    result = await vault.restore(CID, text)
    assert "Alice" in result
    assert "9123-4567" in result
    assert "VAULT_TOKEN_AAAA" not in result
    assert "VAULT_TOKEN_BBBB" not in result


async def test_restore_unknown_token_unchanged(vault: TokenVault) -> None:
    """Token not stored in vault stays in the restored text as-is."""
    # Store a different token, not the one in the text
    await vault.store(CID, {"VAULT_OTHER_XXXX": "something"})

    text = "Check VAULT_UNKNOWN_0000 here"
    result = await vault.restore(CID, text)
    assert "VAULT_UNKNOWN_0000" in result


async def test_delete_removes_all_keys_for_cid(vault: TokenVault) -> None:
    tokens = {"VAULT_DEL_AAAA": "val1", "VAULT_DEL_BBBB": "val2"}
    await vault.store(CID, tokens)

    await vault.delete(CID)

    # After deletion, tokens should remain in text (not replaced)
    result = await vault.restore(CID, "VAULT_DEL_AAAA and VAULT_DEL_BBBB")
    assert "val1" not in result
    assert "val2" not in result


async def test_store_empty_map_is_noop(
    vault: TokenVault, redis: fakeredis.aioredis.FakeRedis
) -> None:
    """Storing an empty dict should not raise and write no keys."""
    await vault.store(CID, {})
    keys = [k async for k in redis.scan_iter(f"vault:{CID}:*")]
    assert keys == []


async def test_store_sets_ttl(
    vault: TokenVault, redis: fakeredis.aioredis.FakeRedis
) -> None:
    """Each stored key must have a positive TTL."""
    await vault.store(CID, {"VAULT_TTL_CCCC": "original"})
    key = f"vault:{CID}:VAULT_TTL_CCCC".encode()
    pttl = await redis.pttl(key)
    # pttl is in milliseconds; must be positive (key has an expiry set)
    assert pttl > 0


async def test_key_format_is_vault_cid_token(
    vault: TokenVault, redis: fakeredis.aioredis.FakeRedis
) -> None:
    """The stored key must follow the format vault:{cid}:{token}."""
    token = "VAULT_FMT_DDDD"
    await vault.store(CID, {token: "some_value"})

    expected_key = f"vault:{CID}:{token}".encode()
    value = await redis.get(expected_key)
    assert value is not None
    assert value.decode() == "some_value"
