"""Bedrock runtime client factory.

Non-negotiable: all LLM calls go through this module.
No import anthropic, no import openai (CI enforced — see .github/workflows/ci.yml).
Bedrock invocation logging is disabled by Terraform (CLAUDE.md §3.7).

Models must use cross-region inference profile IDs (apac.* prefix), not raw model IDs.
Raw model IDs fail with "on-demand throughput not supported" in ap-southeast-1.
"""

from __future__ import annotations

import json
from typing import Any

import aioboto3  # type: ignore[import-untyped]
import botocore.exceptions

from shared.errors import BedrockError, BedrockTimeout

BEDROCK_REGION: str = "ap-southeast-1"

# Maps inference profile ID prefix to the AWS region that serves it.
# apac.* profiles are served from ap-southeast-1 (Singapore cluster).
# us.* profiles are served from us-east-1.
_PREFIX_TO_REGION: dict[str, str] = {
    "apac.": "ap-southeast-1",
    "us.":   "us-east-1",
    "eu.":   "eu-west-1",
}


def _region_for_model(model_id: str, default: str = BEDROCK_REGION) -> str:
    """Return the correct Bedrock endpoint region for a given inference profile ID."""
    for prefix, region in _PREFIX_TO_REGION.items():
        if model_id.startswith(prefix):
            return region
    return default


class BedrockRuntime:
    """Async Bedrock runtime client. One instance per process (persistent connections)."""

    def __init__(self, region: str = BEDROCK_REGION) -> None:
        self._session: aioboto3.Session = aioboto3.Session()
        self._region = region

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
            BedrockError: on any other Bedrock or network error.
        """
        invoke_region = _region_for_model(model_id, default=self._region)
        try:
            async with self._session.client(
                "bedrock-runtime", region_name=invoke_region
            ) as client:
                raw_response = await client.invoke_model(
                    modelId=model_id,
                    body=json.dumps(body),
                    contentType="application/json",
                    accept="application/json",
                )
                raw_body: bytes = await raw_response["body"].read()
                result: dict[str, Any] = json.loads(raw_body)
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
            _code = getattr(exc, "response", {}).get("Error", {}).get("Code", type(exc).__name__)
            _log.warning("bedrock.client_error", error_type=type(exc).__name__, error_code=_code, model_id=model_id)
            raise BedrockError(type(exc).__name__) from exc
        except Exception as exc:
            raise BedrockError(type(exc).__name__) from exc


_default_runtime: BedrockRuntime | None = None


def get_bedrock_runtime(region: str = BEDROCK_REGION) -> BedrockRuntime:
    """Return the process-level BedrockRuntime singleton."""
    global _default_runtime  # noqa: PLW0603
    if _default_runtime is None:
        _default_runtime = BedrockRuntime(region=region)
    return _default_runtime


__all__ = ["BEDROCK_REGION", "BedrockRuntime", "get_bedrock_runtime"]
