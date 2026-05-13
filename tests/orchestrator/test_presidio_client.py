"""Unit tests for orchestrator.presidio_client.PresidioClient.

httpx.AsyncClient is replaced with a mock — no real HTTP calls.
asyncio_mode=auto means no @pytest.mark.asyncio needed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import httpx
import pytest

from orchestrator.presidio_client import PresidioClient
from shared.errors import PresidioError
from shared.models import EntityType

# A fixed UUID used for correlation-id tests
_FIXED_UUID: UUID = UUID("12345678-1234-5678-1234-567812345678")

BASE_URL = "http://presidio.test"
CID_STR = str(_FIXED_UUID)


# =============================================================================
# Helpers
# =============================================================================


def make_client() -> tuple[PresidioClient, AsyncMock]:
    """Create a PresidioClient with its internal httpx client replaced by a mock."""
    client = PresidioClient(BASE_URL)
    mock_http = AsyncMock()
    client._client = mock_http  # type: ignore[assignment]
    return client, mock_http


def make_http_response(data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()  # no-op by default
    resp.status_code = status_code
    return resp


# =============================================================================
# Tests
# =============================================================================


async def test_clean_text_returns_unredacted_result() -> None:
    client, mock_http = make_client()
    resp = make_http_response(
        {"redacted_text": "Hello world", "entity_types": [], "entity_count": 0}
    )
    mock_http.post = AsyncMock(return_value=resp)

    with patch(
        "orchestrator.presidio_client.get_correlation_id",
        return_value=_FIXED_UUID,
    ):
        result = await client.anonymize("Hello world", CID_STR)

    assert result.was_redacted is False
    assert result.entity_count == 0
    assert result.entity_types_found == ()


async def test_redacted_text_returns_entity_types() -> None:
    client, mock_http = make_client()
    resp = make_http_response(
        {
            "redacted_text": "My NRIC is VAULT_TOKEN_XYZ",
            "entity_types": ["SG_NRIC"],
            "entity_count": 1,
        }
    )
    mock_http.post = AsyncMock(return_value=resp)

    with patch(
        "orchestrator.presidio_client.get_correlation_id",
        return_value=_FIXED_UUID,
    ):
        result = await client.anonymize("My NRIC is S1234567A", CID_STR)

    assert EntityType.SG_NRIC in result.entity_types_found
    assert result.was_redacted is True


async def test_unknown_entity_type_is_skipped() -> None:
    client, mock_http = make_client()
    resp = make_http_response(
        {
            "redacted_text": "some text",
            "entity_types": ["UNKNOWN_TYPE"],
            "entity_count": 1,
        }
    )
    mock_http.post = AsyncMock(return_value=resp)

    with patch(
        "orchestrator.presidio_client.get_correlation_id",
        return_value=_FIXED_UUID,
    ):
        result = await client.anonymize("some text", CID_STR)

    assert result.entity_types_found == ()


async def test_entity_count_from_response() -> None:
    client, mock_http = make_client()
    resp = make_http_response(
        {
            "redacted_text": "X Y Z",
            "entity_types": ["SG_NRIC", "CREDIT_CARD", "PHONE_NUMBER"],
            "entity_count": 3,
        }
    )
    mock_http.post = AsyncMock(return_value=resp)

    with patch(
        "orchestrator.presidio_client.get_correlation_id",
        return_value=_FIXED_UUID,
    ):
        result = await client.anonymize("original text", CID_STR)

    assert result.entity_count == 3


async def test_timeout_raises_presidio_error() -> None:
    client, mock_http = make_client()
    mock_http.post = AsyncMock(
        side_effect=httpx.TimeoutException("timed out", request=MagicMock())
    )

    with patch(
        "orchestrator.presidio_client.get_correlation_id",
        return_value=_FIXED_UUID,
    ):
        with pytest.raises(PresidioError):
            await client.anonymize("some text", CID_STR)


async def test_http_error_raises_presidio_error() -> None:
    client, mock_http = make_client()
    bad_resp = make_http_response({}, status_code=500)
    bad_resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "500 server error",
            request=MagicMock(),
            response=MagicMock(),
        )
    )
    mock_http.post = AsyncMock(return_value=bad_resp)

    with patch(
        "orchestrator.presidio_client.get_correlation_id",
        return_value=_FIXED_UUID,
    ):
        with pytest.raises(PresidioError):
            await client.anonymize("some text", CID_STR)


async def test_generic_exception_raises_presidio_error() -> None:
    client, mock_http = make_client()
    mock_http.post = AsyncMock(side_effect=RuntimeError("unexpected"))

    with patch(
        "orchestrator.presidio_client.get_correlation_id",
        return_value=_FIXED_UUID,
    ):
        with pytest.raises(PresidioError):
            await client.anonymize("some text", CID_STR)


async def test_correct_url_called() -> None:
    client, mock_http = make_client()
    resp = make_http_response({"redacted_text": "ok", "entity_types": [], "entity_count": 0})
    mock_http.post = AsyncMock(return_value=resp)

    with patch(
        "orchestrator.presidio_client.get_correlation_id",
        return_value=_FIXED_UUID,
    ):
        await client.anonymize("hello", CID_STR)

    mock_http.post.assert_called_once()
    call_args = mock_http.post.call_args
    # First positional arg is the URL
    called_url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
    assert called_url == f"{BASE_URL}/anonymize"


async def test_correlation_id_in_request_body() -> None:
    client, mock_http = make_client()
    resp = make_http_response({"redacted_text": "ok", "entity_types": [], "entity_count": 0})
    mock_http.post = AsyncMock(return_value=resp)

    with patch(
        "orchestrator.presidio_client.get_correlation_id",
        return_value=_FIXED_UUID,
    ):
        await client.anonymize("hello", CID_STR)

    call_args = mock_http.post.call_args
    json_body: dict = call_args.kwargs.get("json", {})
    assert json_body.get("correlation_id") == CID_STR
