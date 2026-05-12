"""Output redactor: restores vault tokens in vendor responses.

After a vendor responds, this module:
1. Restores VAULT_* tokens back to their original values.
2. Strips any remaining VAULT_* tokens (expired or unexpected) with [REDACTED].

See CLAUDE.md §7 Redactor — "Output leak detector runs on the restored vendor
response and strips any unexpected PII."
"""

from __future__ import annotations

from uuid import UUID

from redactor.vault import VAULT_TOKEN_RE, TokenVault


class OutputRedactor:
    """Restores and sanitises vault tokens in vendor responses."""

    def __init__(self, vault: TokenVault) -> None:
        self._vault = vault

    async def restore(self, text: str, correlation_id: UUID) -> str:
        """Replace all VAULT_* tokens with their original values from the vault.

        Tokens not found in the vault (expired/unknown) are left as-is.
        """
        return await self._vault.restore(correlation_id, text)

    async def restore_and_check(
        self,
        text: str,
        correlation_id: UUID,
        expected_entity_types: tuple,  # type: ignore[type-arg]
    ) -> str:
        """Restore known tokens, then replace any remaining VAULT_* with [REDACTED].

        The ``expected_entity_types`` parameter is accepted for API consistency
        with the architecture spec (future: cross-check entity types found in
        output vs. input). Currently, any token that survived restoration is
        treated as a leak and stripped.
        """
        restored = await self._vault.restore(correlation_id, text)
        # Any VAULT_* token left after restore was not in the vault
        # (expired or injected by the vendor) — strip it.
        sanitised = VAULT_TOKEN_RE.sub("[REDACTED]", restored)
        return sanitised
