"""Redis token vault for PII de-redaction.

Tokens are stored as vault:{correlation_id}:{token} with a 5-minute TTL.
The TTL is the security boundary — vault keys must never outlive 5 minutes
(CLAUDE.md §7 Redactor).

The vault stores the token→original_value mapping that Presidio returns.
During output restoration, each token in the vendor response is looked up
and replaced with its original value.
"""

from __future__ import annotations

import redis.asyncio as aioredis

from shared.logging import safe_log


class TokenVault:
    def __init__(self, redis: aioredis.Redis, ttl_seconds: int = 300) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    def _key(self, correlation_id: str, token: str) -> str:
        return f"vault:{correlation_id}:{token}"

    async def store(
        self, correlation_id: str, tokens: dict[str, str]
    ) -> None:
        """Store token→original_value pairs with TTL."""
        if not tokens:
            return
        pipe = self._redis.pipeline()
        for token, original in tokens.items():
            k = self._key(correlation_id, token)
            pipe.set(k, original, ex=self._ttl)
        await pipe.execute()
        safe_log.info("orchestrator.vault.stored", entity_count=len(tokens))

    async def restore(self, correlation_id: str, text: str) -> str:
        """Replace all tokens in text with their original values."""
        if "VAULT_" not in text:
            return text

        # Collect all token keys for this correlation_id
        pattern = f"vault:{correlation_id}:*"
        keys: list[bytes] = []
        async for key in self._redis.scan_iter(pattern):
            keys.append(key)

        if not keys:
            return text

        values = await self._redis.mget(*keys)
        restored = text
        for key_bytes, value_bytes in zip(keys, values):
            if value_bytes is None:
                continue
            token = key_bytes.decode().split(":", 2)[2]
            original = value_bytes.decode()
            restored = restored.replace(token, original)

        return restored

    async def delete(self, correlation_id: str) -> None:
        """Eager cleanup — delete all vault keys for this correlation_id."""
        pattern = f"vault:{correlation_id}:*"
        keys: list[bytes] = [key async for key in self._redis.scan_iter(pattern)]
        if keys:
            await self._redis.delete(*keys)
            safe_log.info("orchestrator.vault.deleted", entity_count=len(keys))
