"""Token vault for reversible PII redaction.

Stores vault token → original value mappings in Redis with a TTL.
Key format: vault:{correlation_id}:{token}

See CLAUDE.md §7 Redactor:
  - Token vault keys: vault:{correlation_id}:{token}, TTL 5 minutes.
  - Never longer — that's the security boundary.
"""

from __future__ import annotations

import re
from uuid import UUID

import redis.asyncio as aioredis

# Module-level regex used by other modules (streaming_redactor, output_redactor).
VAULT_TOKEN_RE = re.compile(r"VAULT_[A-F0-9]{12}")


def _vault_key(correlation_id: UUID, token: str) -> str:
    return f"vault:{correlation_id}:{token}"


class TokenVault:
    """Redis-backed vault for VAULT_* token → original value mappings."""

    def __init__(self, redis: aioredis.Redis, ttl_seconds: int = 300) -> None:  # type: ignore[type-arg]
        self._redis = redis
        self._ttl = ttl_seconds

    async def store(self, correlation_id: UUID, token_map: dict[str, str]) -> None:
        """Store all token→original mappings in a pipelined SET with TTL."""
        if not token_map:
            return
        pipe = self._redis.pipeline()
        for token, original in token_map.items():
            pipe.set(_vault_key(correlation_id, token), original, ex=self._ttl)
        await pipe.execute()

    async def restore(self, correlation_id: UUID, text: str) -> str:
        """Replace all VAULT_* tokens in text with their original values.

        Tokens not found in the vault (expired or unknown) are left unchanged.
        """
        tokens = VAULT_TOKEN_RE.findall(text)
        if not tokens:
            return text

        keys = [_vault_key(correlation_id, token) for token in tokens]
        values = await self._redis.mget(keys)

        for token, value in zip(tokens, values):
            if value is not None:
                original = value.decode() if isinstance(value, bytes) else value
                text = text.replace(token, original, 1)

        return text

    async def delete_all(self, correlation_id: UUID) -> int:
        """Delete all vault keys for this correlation_id. Returns count deleted."""
        pattern = f"vault:{correlation_id}:*"
        keys_to_delete: list[bytes] = []
        async for key in self._redis.scan_iter(pattern):
            keys_to_delete.append(key)

        if not keys_to_delete:
            return 0

        deleted: int = await self._redis.delete(*keys_to_delete)
        return deleted
