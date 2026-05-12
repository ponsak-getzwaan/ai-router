"""Redactor configuration.

All settings are read from environment variables with the REDACTOR_ prefix.
See CLAUDE.md §7 Redactor.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class RedactorConfig(BaseSettings):
    """Settings for the Redactor layer.

    Loaded from environment variables (prefix: REDACTOR_).
    """

    model_config = {"env_prefix": "REDACTOR_"}

    presidio_url: str = "http://presidio.internal:8080"
    vault_ttl_seconds: int = 300
    http_timeout_seconds: float = 5.0
