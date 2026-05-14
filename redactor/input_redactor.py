"""Input redactor: sends text to the Presidio sidecar and vaults the tokens.

The Presidio sidecar is a persistent ECS Fargate service called over
VPC-internal HTTP (CLAUDE.md §7 Redactor — no Presidio imports here).

See also: presidio_sidecar/main.py for the /anonymize request/response shape.
"""

from __future__ import annotations

from uuid import UUID

import httpx

from redactor.vault import TokenVault
from shared.models import EntityType, RedactionResult


class InputRedactor:
    """Sends text to the Presidio sidecar and vaults the returned tokens.

    Parameters
    ----------
    presidio_url:
        Base URL of the Presidio sidecar (e.g. ``http://presidio.internal:8080``).
    vault:
        Token vault to store mappings in.
    http_timeout:
        Timeout in seconds for the HTTP call to the sidecar.
    client:
        Optional pre-built ``httpx.AsyncClient`` for dependency injection in
        tests. If ``None`` a new client is created per call.
    """

    def __init__(
        self,
        presidio_url: str,
        vault: TokenVault,
        http_timeout: float = 5.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._presidio_url = presidio_url.rstrip("/")
        self._vault = vault
        self._http_timeout = http_timeout
        self._client = client

    async def redact(self, text: str, correlation_id: UUID) -> RedactionResult:
        """POST text to the Presidio sidecar and return a RedactionResult.

        Tokens are stored in the vault keyed by correlation_id.
        Unknown entity type strings from the sidecar are silently skipped.
        """
        payload = {
            "text": text,
            "correlation_id": str(correlation_id),
        }

        if self._client is not None:
            response = await self._client.post(
                f"{self._presidio_url}/anonymize",
                json=payload,
                timeout=self._http_timeout,
            )
        else:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self._presidio_url}/anonymize",
                    json=payload,
                    timeout=self._http_timeout,
                )

        response.raise_for_status()
        data = response.json()

        token_map: dict[str, str] = data.get("tokens", {})
        raw_entity_types: list[str] = data.get("entity_types", [])
        entity_count: int = data.get("entity_count", 0)
        redacted_text: str = data.get("redacted_text", text)

        # Store vault tokens (no-op if empty)
        await self._vault.store(correlation_id, token_map)

        # Map entity type strings to the EntityType enum, skip unknowns
        entity_types: list[EntityType] = []
        for raw in raw_entity_types:
            try:
                entity_types.append(EntityType(raw))
            except ValueError:
                pass  # unknown entity type — skip silently

        was_redacted = bool(token_map)

        return RedactionResult(
            redacted_message=redacted_text,
            entity_types_found=tuple(entity_types),
            entity_count=entity_count,
            was_redacted=was_redacted,
            correlation_id=correlation_id,
        )
