"""Bedrock runtime client factory.

Non-negotiable: all LLM calls go through this module.
No import anthropic, no import openai (CI enforced — see .github/workflows/ci.yml).
Bedrock invocation logging is disabled by Terraform (CLAUDE.md §3.7).

Models must use cross-region inference profile IDs (apac.* or global.* prefix), not
raw model IDs. Raw model IDs fail with "on-demand throughput not supported".
global.* profiles are invoked from ap-southeast-1 but may route compute globally
(data-residency trade-off accepted per CLAUDE.md §3.9 note).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import aioboto3  # type: ignore[import-untyped]
import botocore.exceptions

from shared.errors import BedrockError, BedrockTimeout

# Transient Bedrock error codes that are safe to retry.
_RETRYABLE_CODES: frozenset[str] = frozenset({"ThrottlingException", "ServiceUnavailableException"})
_MAX_RETRIES: int = 1
_RETRY_BASE_SECONDS: float = 0.5  # one retry after 0.5 s

BEDROCK_REGION: str = "ap-southeast-1"

# Maps inference profile ID prefix to the AWS region that serves it.
# apac.* profiles are served from ap-southeast-1 (Singapore cluster).
# global.* profiles are invoked from ap-southeast-1 but route compute globally.
# us.* profiles are served from us-east-1.
_PREFIX_TO_REGION: dict[str, str] = {
    "apac.":   "ap-southeast-1",
    "global.": "ap-southeast-1",
    "us.":     "us-east-1",
    "eu.":     "eu-west-1",
}


def _region_for_model(model_id: str, default: str = BEDROCK_REGION) -> str:
    """Return the correct Bedrock endpoint region for a given inference profile ID."""
    for prefix, region in _PREFIX_TO_REGION.items():
        if model_id.startswith(prefix):
            return region
    return default


class BedrockRuntime:
    """Async Bedrock runtime client. One instance per process (persistent connections).

    Call ``await runtime.connect()`` once at startup to open the persistent
    aiohttp session; call ``await runtime.close()`` on shutdown. If connect()
    has not been called, invoke_model falls back to creating a short-lived
    client per call (original behaviour, but no connection pooling).
    """

    def __init__(self, region: str = BEDROCK_REGION) -> None:
        self._session: aioboto3.Session = aioboto3.Session()
        self._region = region
        # Persistent client — populated by connect(), cleared by close().
        # Keyed by region so apac.* and us.* models each get their own pool.
        self._clients: dict[str, Any] = {}
        self._client_ctxs: dict[str, Any] = {}

    async def connect(self, regions: list[str] | None = None) -> None:
        """Open persistent Bedrock clients for the given regions.

        Defaults to just the primary region. Call once at service startup
        so the TLS handshake cost is paid before the first real request.
        """
        for region in (regions or [self._region]):
            ctx = self._session.client("bedrock-runtime", region_name=region)
            self._clients[region] = await ctx.__aenter__()
            self._client_ctxs[region] = ctx

    async def close(self) -> None:
        """Close all persistent clients. Call during service shutdown."""
        for region, ctx in self._client_ctxs.items():
            try:
                await ctx.__aexit__(None, None, None)
            except Exception:
                pass
        self._clients.clear()
        self._client_ctxs.clear()

    async def invoke_model(
        self,
        model_id: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """Invoke a Bedrock model and return the parsed response body.

        Args:
            model_id: Cross-region inference profile ID, e.g. apac.anthropic.claude-haiku-4-5-...
                      The endpoint region is derived automatically from the ID prefix
                      (apac.* → ap-southeast-1, us.* → us-east-1).
            body: Request payload (Anthropic Messages API format for Claude models).

        Raises:
            BedrockTimeout: on read or connect timeout.
            BedrockError: on any other Bedrock or network error (after retries).

        ThrottlingException and ServiceUnavailableException are retried up to
        _MAX_RETRIES times with exponential backoff (_RETRY_BASE_SECONDS * 2^attempt).
        The Bouncer's asyncio.wait_for(timeout=0.2) naturally cancels retry sleeps
        if the budget is exceeded, preserving fail-open behaviour.
        """
        invoke_region = _region_for_model(model_id, default=self._region)
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES + 1):
            if attempt:
                await asyncio.sleep(_RETRY_BASE_SECONDS * (2 ** (attempt - 1)))
            try:
                if invoke_region in self._clients:
                    result = await self._invoke_with(
                        self._clients[invoke_region], model_id, body
                    )
                else:
                    # Fallback: short-lived client (no persistent pool for this region).
                    async with self._session.client(
                        "bedrock-runtime", region_name=invoke_region
                    ) as client:
                        result = await self._invoke_with(client, model_id, body)
                return result
            except (
                botocore.exceptions.ReadTimeoutError,
                botocore.exceptions.ConnectTimeoutError,
            ) as exc:
                raise BedrockTimeout(type(exc).__name__) from exc
            except (
                botocore.exceptions.ClientError,
                botocore.exceptions.BotoCoreError,
            ) as exc:
                from shared.logging import safe_log as _log
                _resp = getattr(exc, "response", None) or {}
                _code = _resp.get("Error", {}).get("Code", type(exc).__name__)
                _log.warning(
                    "bedrock.client_error",
                    error_type=type(exc).__name__,
                    error_code=_code,
                    model_id=model_id,
                    attempt=attempt,
                )
                if _code in _RETRYABLE_CODES and attempt < _MAX_RETRIES:
                    last_exc = exc
                    continue
                raise BedrockError(type(exc).__name__) from exc
            except Exception as exc:
                from shared.logging import safe_log as _log
                _log.warning(
                    "bedrock.unexpected_error",
                    error_type=type(exc).__name__,
                    model_id=model_id,
                    attempt=attempt,
                )
                raise BedrockError(type(exc).__name__) from exc

        raise BedrockError(type(last_exc).__name__ if last_exc else "ThrottlingException") from last_exc

    @staticmethod
    async def _invoke_with(client: Any, model_id: str, body: dict[str, Any]) -> dict[str, Any]:
        raw_response = await client.invoke_model(
            modelId=model_id,
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json",
        )
        raw_body: bytes = await raw_response["body"].read()
        return json.loads(raw_body)  # type: ignore[no-any-return]


_default_runtime: BedrockRuntime | None = None


def get_bedrock_runtime(region: str = BEDROCK_REGION) -> BedrockRuntime:
    """Return the process-level BedrockRuntime singleton."""
    global _default_runtime  # noqa: PLW0603
    if _default_runtime is None:
        _default_runtime = BedrockRuntime(region=region)
    return _default_runtime


__all__ = ["BEDROCK_REGION", "BedrockRuntime", "get_bedrock_runtime"]
