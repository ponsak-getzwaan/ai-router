"""Fixtures for orchestrator unit tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _mock_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace fire-and-forget metrics with no-ops.

    emit_classifier and emit_strategist are called via asyncio.create_task()
    in pipeline_driver.py. In tests they attempt real aiohttp/CloudWatch
    connections that never complete, leaving dangling tasks that cause
    PytestUnraisableExceptionWarning failures on teardown.
    """
    async def _noop(*args: object, **kwargs: object) -> None:
        pass

    monkeypatch.setattr("orchestrator.pipeline_driver.emit_classifier", _noop)
    monkeypatch.setattr("orchestrator.pipeline_driver.emit_strategist", _noop)
