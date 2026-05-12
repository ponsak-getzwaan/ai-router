"""Unit tests for redactor.output_redactor.OutputRedactor.

Uses fakeredis for an in-process async Redis implementation.
asyncio_mode = "auto" — no @pytest.mark.asyncio needed.
"""

from __future__ import annotations

from uuid import uuid4

import fakeredis.aioredis as fakeredis
import pytest

from redactor.output_redactor import OutputRedactor
from redactor.vault import TokenVault


@pytest.fixture
async def redis():  # type: ignore[misc]
    r = fakeredis.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
async def vault(redis):  # type: ignore[misc]
    return TokenVault(redis, ttl_seconds=300)


@pytest.fixture
def output_redactor(vault: TokenVault) -> OutputRedactor:
    return OutputRedactor(vault)


async def test_restore_replaces_known_tokens(
    output_redactor: OutputRedactor, vault: TokenVault
) -> None:
    cid = uuid4()
    await vault.store(cid, {"VAULT_AABBCCDDEEFF": "S1234567A"})

    result = await output_redactor.restore(
        "Your NRIC VAULT_AABBCCDDEEFF has been processed.", cid
    )
    assert result == "Your NRIC S1234567A has been processed."


async def test_restore_and_check_strips_unknown_vault_tokens(
    output_redactor: OutputRedactor,
) -> None:
    cid = uuid4()
    # VAULT_DEADBEEF1234 is a valid-format token but is NOT stored in the vault
    result = await output_redactor.restore_and_check(
        "See VAULT_DEADBEEF1234 here.", cid, expected_entity_types=()
    )
    assert result == "See [REDACTED] here."
    assert "VAULT_" not in result


async def test_restore_and_check_known_token_not_stripped(
    output_redactor: OutputRedactor, vault: TokenVault
) -> None:
    cid = uuid4()
    await vault.store(cid, {"VAULT_AABBCCDDEEFF": "S1234567A"})

    result = await output_redactor.restore_and_check(
        "Value is VAULT_AABBCCDDEEFF.", cid, expected_entity_types=("SG_NRIC",)
    )
    # The known token should be restored, not replaced with [REDACTED]
    assert result == "Value is S1234567A."
    assert "[REDACTED]" not in result


async def test_clean_text_returned_unchanged(output_redactor: OutputRedactor) -> None:
    cid = uuid4()
    text = "This response has no vault tokens at all."
    result = await output_redactor.restore(text, cid)
    assert result == text


async def test_multiple_tokens_all_restored(
    output_redactor: OutputRedactor, vault: TokenVault
) -> None:
    cid = uuid4()
    await vault.store(
        cid,
        {
            "VAULT_AABBCCDDEEFF": "S1234567A",
            "VAULT_112233445566": "F9876543Z",
            "VAULT_CCDDEE112233": "12345678A",
        },
    )

    text = (
        "NRIC VAULT_AABBCCDDEEFF, FIN VAULT_112233445566, UEN VAULT_CCDDEE112233."
    )
    result = await output_redactor.restore(text, cid)
    assert "S1234567A" in result
    assert "F9876543Z" in result
    assert "12345678A" in result
    assert "VAULT_" not in result
