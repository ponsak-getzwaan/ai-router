"""HTTP client for the Presidio sidecar.

The Presidio sidecar runs as a separate ECS Fargate service and is reached
over VPC-internal HTTP (http://presidio.ai-router.internal:8080).
The ~200MB spaCy model must stay resident in the sidecar process —
it cannot be imported into the orchestrator (CLAUDE.md §7 Redactor).
"""

from __future__ import annotations

import hashlib
from typing import Any

import httpx

from shared.correlation import get_correlation_id
from shared.errors import PresidioError
from shared.logging import safe_log
from shared.models import EntityType, RedactionResult


class PresidioClient:
    def __init__(self, base_url: str, timeout_s: float = 5.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_s
        self._client = httpx.AsyncClient(timeout=timeout_s)

    async def anonymize(self, raw_message: str, correlation_id_str: str) -> RedactionResult:
        """Send raw message to Presidio and return the RedactionResult.

        Raises:
            PresidioError: if the sidecar is unreachable or returns an error.
        """
        try:
            response = await self._client.post(
                f"{self._base_url}/anonymize",
                json={"text": raw_message, "correlation_id": correlation_id_str},
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
        except httpx.TimeoutException as exc:
            raise PresidioError(type(exc).__name__) from exc
        except httpx.HTTPStatusError as exc:
            raise PresidioError(type(exc).__name__) from exc
        except Exception as exc:
            raise PresidioError(type(exc).__name__) from exc

        redacted = str(data.get("redacted_text", raw_message))
        entity_types_raw: list[str] = data.get("entity_types", [])
        entity_count: int = int(data.get("entity_count", 0))

        entity_types: tuple[EntityType, ...] = tuple(
            EntityType(et) for et in entity_types_raw if et in EntityType.__members__
        )

        hashlib.sha256(raw_message.encode()).hexdigest()

        safe_log.info(
            "orchestrator.presidio.anonymized",
            entity_count=entity_count,
            entity_types_found=list(entity_types),
            was_redacted=bool(entity_types),
        )

        return RedactionResult(
            redacted_message=redacted,
            entity_types_found=entity_types,
            entity_count=entity_count,
            was_redacted=bool(entity_types),
            correlation_id=get_correlation_id(),
        )

    async def aclose(self) -> None:
        await self._client.aclose()
