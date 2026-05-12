"""Streaming redactor: buffers vendor response chunks and restores tokens.

Tokens can span chunk boundaries. We keep the last SAFETY_MARGIN bytes in the
buffer at all times so a VAULT_* token (14 chars) split across a boundary is
never emitted before the full token arrives.

Constants (do not tune without re-running the golden tests — CLAUDE.md §7):
  BUFFER_SIZE   = 200   The buffer length that triggers an emit.
  SAFETY_MARGIN = 50    Chars kept back in the buffer after each emit.
"""

from __future__ import annotations

from uuid import UUID

from redactor.vault import TokenVault

BUFFER_SIZE: int = 200
SAFETY_MARGIN: int = 50


class StreamingRedactor:
    """Buffer-and-restore streaming redactor for a single response stream.

    Each instance is scoped to one correlation_id. Create a new instance
    per request.
    """

    def __init__(self, vault: TokenVault, correlation_id: UUID) -> None:
        self._vault = vault
        self._correlation_id = correlation_id
        self._buffer: str = ""

    async def feed(self, chunk: str) -> str:
        """Append chunk to the internal buffer.

        When the buffer reaches BUFFER_SIZE, emit all but the last
        SAFETY_MARGIN chars (after restoring tokens), retain the rest.

        Returns the restored output; empty string if nothing emitted yet.
        """
        self._buffer += chunk

        if len(self._buffer) < BUFFER_SIZE:
            return ""

        emit_length = len(self._buffer) - SAFETY_MARGIN
        to_emit = self._buffer[:emit_length]
        self._buffer = self._buffer[emit_length:]

        restored = await self._vault.restore(self._correlation_id, to_emit)
        return restored

    async def flush(self) -> str:
        """Restore and return all remaining buffered content, then clear."""
        if not self._buffer:
            return ""
        remaining = self._buffer
        self._buffer = ""
        restored = await self._vault.restore(self._correlation_id, remaining)
        return restored
