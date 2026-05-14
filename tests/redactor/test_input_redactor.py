"""Unit tests for redactor.input_redactor.InputRedactor.

The Presidio sidecar HTTP call is mocked via unittest.mock.AsyncMock so these
tests run without a real sidecar. The httpx.AsyncClient is injected via the
optional ``client`` parameter added to InputRedactor for testability.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import fakeredis.aioredis as fakeredis
import httpx
import pytest

from redactor.input_redactor import InputRedactor
from redactor.vault import TokenVault
from shared.models import EntityType


def _make_mock_client(response_data: dict) -> httpx.AsyncClient:
    """Build a mock AsyncClient whose post() returns response_data."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock(return_value=None)
    mock_response.json = MagicMock(return_value=response_data)

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)
    return mock_client  # type: ignore[return-value]


@pytest.fixture
async def redis():  # type: ignore[misc]
    r = fakeredis.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
async def vault(redis):  # type: ignore[misc]
    return TokenVault(redis, ttl_seconds=300)


async def test_clean_text_returns_unredacted_result(vault: TokenVault) -> None:
    cid = uuid4()
    sidecar_response = {
        "redacted_text": "Hello world",
        "entity_types": [],
        "entity_count": 0,
        "tokens": {},
    }
    client = _make_mock_client(sidecar_response)
    redactor = InputRedactor("http://presidio.internal:8080", vault, client=client)

    result = await redactor.redact("Hello world", cid)

    assert result.was_redacted is False
    assert result.entity_count == 0
    assert result.entity_types_found == ()
    assert result.redacted_message == "Hello world"
    assert result.correlation_id == cid


async def test_redacted_text_stores_tokens_in_vault(redis, vault: TokenVault) -> None:
    cid = uuid4()
    token = "VAULT_AABBCCDDEEFF"
    sidecar_response = {
        "redacted_text": f"My NRIC is {token}.",
        "entity_types": ["SG_NRIC"],
        "entity_count": 1,
        "tokens": {token: "S1234567A"},
    }
    client = _make_mock_client(sidecar_response)
    redactor = InputRedactor("http://presidio.internal:8080", vault, client=client)

    result = await redactor.redact("My NRIC is S1234567A.", cid)

    assert result.was_redacted is True
    # Vault should have the token stored
    key = f"vault:{cid}:{token}"
    value = await redis.get(key)
    assert value is not None
    assert value.decode() == "S1234567A"


async def test_result_has_correct_entity_types(vault: TokenVault) -> None:
    cid = uuid4()
    sidecar_response = {
        "redacted_text": "Redacted",
        "entity_types": ["SG_NRIC", "SG_FIN"],
        "entity_count": 2,
        "tokens": {"VAULT_AABBCCDDEEFF": "S1234567A", "VAULT_112233445566": "F9876543Z"},
    }
    client = _make_mock_client(sidecar_response)
    redactor = InputRedactor("http://presidio.internal:8080", vault, client=client)

    result = await redactor.redact("text", cid)

    assert EntityType.SG_NRIC in result.entity_types_found
    assert EntityType.SG_FIN in result.entity_types_found


async def test_unknown_entity_types_are_skipped(vault: TokenVault) -> None:
    cid = uuid4()
    sidecar_response = {
        "redacted_text": "Redacted",
        "entity_types": ["SG_NRIC", "UNKNOWN_TYPE", "FUTURE_TYPE"],
        "entity_count": 3,
        "tokens": {"VAULT_AABBCCDDEEFF": "S1234567A"},
    }
    client = _make_mock_client(sidecar_response)
    redactor = InputRedactor("http://presidio.internal:8080", vault, client=client)

    result = await redactor.redact("text", cid)

    # Only known types are in the result
    assert EntityType.SG_NRIC in result.entity_types_found
    for et in result.entity_types_found:
        assert et in EntityType.__members__.values(), f"Unknown EntityType in result: {et}"


async def test_http_error_propagates(vault: TokenVault) -> None:
    cid = uuid4()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "500 Internal Server Error",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )
    )
    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    redactor = InputRedactor("http://presidio.internal:8080", vault, client=mock_client)  # type: ignore[arg-type]

    with pytest.raises(httpx.HTTPStatusError):
        await redactor.redact("text", cid)


async def test_no_injected_client_creates_own_client(vault: TokenVault) -> None:
    """When client=None, InputRedactor opens its own httpx.AsyncClient per call."""
    cid = uuid4()
    sidecar_response = {
        "redacted_text": "Hello",
        "entity_types": [],
        "entity_count": 0,
        "tokens": {},
    }
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock(return_value=None)
    mock_response.json = MagicMock(return_value=sidecar_response)

    mock_inner = AsyncMock()
    mock_inner.post = AsyncMock(return_value=mock_response)

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_inner)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("redactor.input_redactor.httpx.AsyncClient", return_value=mock_cm):
        redactor = InputRedactor("http://presidio.internal:8080", vault)  # no client=
        result = await redactor.redact("Hello", cid)

    assert result.was_redacted is False
    mock_inner.post.assert_called_once()


async def test_correlation_id_sent_to_sidecar(vault: TokenVault) -> None:
    cid = uuid4()
    sidecar_response = {
        "redacted_text": "text",
        "entity_types": [],
        "entity_count": 0,
        "tokens": {},
    }
    client = _make_mock_client(sidecar_response)
    redactor = InputRedactor("http://presidio.internal:8080", vault, client=client)

    await redactor.redact("text", cid)

    # Check that post was called with the correlation_id as string
    call_kwargs = client.post.call_args
    # Access the json kwarg from the call
    _, kwargs = call_kwargs
    assert kwargs["json"]["correlation_id"] == str(cid)
