"""Session history: Redis-backed per-session conversation turns.

Stores redacted turns only — user messages as vault-tokenized text,
assistant responses as pre-restore vendor output. Both are PII-safe.

Key schema: history:{session_id}
TTL: 30 minutes (resets on every append)
Cap: 10 turns (5 user+assistant exchanges); oldest are dropped first.
"""

from __future__ import annotations

import json

import redis.asyncio as aioredis

from shared.logging import safe_log

_KEY_PREFIX = "history:"
_DEFAULT_MAX_TURNS = 10
_DEFAULT_TTL = 1800


class SessionHistory:
    def __init__(
        self,
        redis: aioredis.Redis,
        max_turns: int = _DEFAULT_MAX_TURNS,
        ttl_seconds: int = _DEFAULT_TTL,
    ) -> None:
        self._redis = redis
        self._max_turns = max_turns
        self._ttl = ttl_seconds

    def _key(self, session_id: str) -> str:
        return f"{_KEY_PREFIX}{session_id}"

    async def get(self, session_id: str) -> list[dict[str, str]]:
        """Return stored turns, oldest first. Empty list on miss or error."""
        try:
            raw: bytes | None = await self._redis.get(self._key(session_id))
            if not raw:
                return []
            result: list[dict[str, str]] = json.loads(raw)
            return result
        except Exception as exc:
            safe_log.warning("history.get_error", error_type=type(exc).__name__)
            return []

    async def append(
        self,
        session_id: str,
        user_message: str,
        assistant_response: str,
    ) -> None:
        """Append one exchange and refresh the TTL.

        Both strings must be in redacted (vault-tokenized) form — the caller
        is responsible for passing pre-restore content.
        """
        try:
            key = self._key(session_id)
            raw: bytes | None = await self._redis.get(key)
            turns: list[dict[str, str]] = json.loads(raw) if raw else []
            turns.append({"role": "user", "content": user_message})
            turns.append({"role": "assistant", "content": assistant_response})
            if len(turns) > self._max_turns:
                turns = turns[-self._max_turns:]
            await self._redis.set(key, json.dumps(turns), ex=self._ttl)
        except Exception as exc:
            safe_log.warning("history.append_error", error_type=type(exc).__name__)


__all__ = ["SessionHistory"]
