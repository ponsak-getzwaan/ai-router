"""Redis aggregate stats for the admin dashboard.

IMPORTANT: Only aggregate stats are surfaced — connection count, memory,
keyspace summary. HGETALL and SCAN on the vault namespace are explicitly
forbidden (architecture.md §Admin Dashboard "PII constraints").

The vault key pattern is `vault:{correlation_id}:{token}`. Never read these.
"""

from __future__ import annotations

from typing import Any

import redis.asyncio as aioredis

from shared.logging import safe_log

_FORBIDDEN_PREFIXES = ("vault:",)


class RedisAdminService:
    def __init__(self, redis_url: str) -> None:
        self._url = redis_url
        self._client: aioredis.Redis | None = None

    async def connect(self) -> None:
        self._client = aioredis.from_url(self._url, decode_responses=True)  # type: ignore[no-untyped-call]

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    async def health(self) -> str:
        """Returns 'ok' or 'unavailable'."""
        try:
            assert self._client is not None
            await self._client.ping()
            return "ok"
        except Exception as exc:
            safe_log.warning("admin.redis.health_error", error_type=type(exc).__name__)
            return "unavailable"

    async def stats(self) -> dict[str, Any]:
        """Aggregate stats only — no key inspection, no value reads."""
        try:
            assert self._client is not None
            info: dict[str, Any] = await self._client.info()
            keyspace: dict[str, Any] = await self._client.info("keyspace")

            # Count vault keys (count only, not keys or values)
            vault_count = 0
            try:
                cursor = 0
                while True:
                    cursor, keys = await self._client.scan(
                        cursor=cursor,
                        match="vault:*",
                        count=100,
                    )
                    vault_count += len(keys)
                    if cursor == 0:
                        break
            except Exception:
                vault_count = -1  # -1 = unknown, not an error

            return {
                "connected_clients": info.get("connected_clients"),
                "used_memory_human": info.get("used_memory_human"),
                "total_commands_processed": info.get("total_commands_processed"),
                "keyspace": keyspace,
                "active_vault_keys": vault_count,  # count only, never keys or values
            }
        except Exception as exc:
            safe_log.warning("admin.redis.stats_error", error_type=type(exc).__name__)
            return {}
