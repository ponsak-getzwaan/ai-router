"""Cognito JWT validation for the admin FastAPI app.

No API Gateway authorizer exists in Phase 1, so the admin service validates
JWTs directly using Cognito's JWKS endpoint.

Access tokens (not ID tokens) are expected in the Authorization header.
Cognito access tokens use RS256 and have token_use=access; they do not carry
an aud claim (use client_id from iss+sub instead).
"""

from __future__ import annotations

import time
from functools import lru_cache
from typing import Any

import httpx
import jwt
import jwt.algorithms
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from admin.config import AdminConfig
from shared.logging import safe_log


@lru_cache(maxsize=1)
def _config() -> AdminConfig:
    return AdminConfig()


# Module-level JWKS cache — refreshed every hour, shared across requests
_jwks_keys: list[dict[str, Any]] = []
_jwks_fetched_at: float = 0.0
_JWKS_TTL_S: float = 3600.0

_bearer = HTTPBearer(auto_error=True)


def _issuer(cfg: AdminConfig) -> str:
    return f"https://cognito-idp.{cfg.cognito_region}.amazonaws.com/{cfg.cognito_user_pool_id}"


async def _get_jwks(cfg: AdminConfig) -> list[dict[str, Any]]:
    global _jwks_keys, _jwks_fetched_at
    if time.monotonic() - _jwks_fetched_at < _JWKS_TTL_S and _jwks_keys:
        return _jwks_keys
    uri = f"{_issuer(cfg)}/.well-known/jwks.json"
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(uri)
        resp.raise_for_status()
    _jwks_keys = resp.json()["keys"]
    _jwks_fetched_at = time.monotonic()
    return _jwks_keys


def _public_key(keys: list[dict[str, Any]], kid: str) -> Any:
    for k in keys:
        if k["kid"] == kid:
            return jwt.algorithms.RSAAlgorithm.from_jwk(k)
    raise HTTPException(status_code=401, detail="unknown_kid")


async def require_cognito_token(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> dict[str, Any]:
    """FastAPI dependency — validates Cognito access token, returns decoded claims."""
    cfg = _config()
    token = credentials.credentials

    try:
        header = jwt.get_unverified_header(token)
        keys = await _get_jwks(cfg)
        public_key = _public_key(keys, header.get("kid", ""))

        claims: dict[str, Any] = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            # Access tokens have no aud — skip audience validation
            options={"verify_aud": False, "verify_exp": True},
            issuer=_issuer(cfg),
        )
    except HTTPException:
        raise
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="token_expired")
    except jwt.InvalidIssuerError:
        raise HTTPException(status_code=401, detail="invalid_issuer")
    except jwt.InvalidTokenError as exc:
        safe_log.warning("admin.auth.invalid_token", error_type=type(exc).__name__)
        raise HTTPException(status_code=401, detail="invalid_token")
    except Exception as exc:
        safe_log.warning("admin.auth.error", error_type=type(exc).__name__)
        raise HTTPException(status_code=401, detail="auth_error")

    if claims.get("token_use") != "access":
        raise HTTPException(status_code=401, detail="not_an_access_token")

    return claims
