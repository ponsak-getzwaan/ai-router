"""Unit tests for redactor.config.RedactorConfig."""

from __future__ import annotations

import pytest

from redactor.config import RedactorConfig


def test_default_values() -> None:
    config = RedactorConfig()
    assert config.presidio_url == "http://presidio.internal:8080"
    assert config.vault_ttl_seconds == 300
    assert config.http_timeout_seconds == 5.0


def test_env_prefix_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDACTOR_PRESIDIO_URL", "http://localhost:9999")
    monkeypatch.setenv("REDACTOR_VAULT_TTL_SECONDS", "600")
    monkeypatch.setenv("REDACTOR_HTTP_TIMEOUT_SECONDS", "2.5")

    config = RedactorConfig()

    assert config.presidio_url == "http://localhost:9999"
    assert config.vault_ttl_seconds == 600
    assert config.http_timeout_seconds == 2.5
