"""Tests for GET /admin/health.

The health endpoint probes DynamoDB, Redis, and SQS independently. A failure
in one service must produce status="degraded" without taking the others down.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from tests.admin.conftest import AdminCtx


class TestHealthAllOk:
    async def test_returns_200(self, ctx: AdminCtx) -> None:
        resp = await ctx.client.get("/admin/api/health")
        assert resp.status_code == 200

    async def test_status_ok_when_all_healthy(self, ctx: AdminCtx) -> None:
        with patch("admin.routers.health.aioboto3") as mock_boto:
            _stub_healthy_dynamo(mock_boto)
            _stub_healthy_sqs(mock_boto)
            resp = await ctx.client.get("/admin/api/health")
        data = resp.json()
        assert data["status"] == "ok"
        assert data["dynamodb"] == "ok"
        assert data["redis"] == "ok"

    async def test_response_has_checked_at_timestamp(self, ctx: AdminCtx) -> None:
        with patch("admin.routers.health.aioboto3") as mock_boto:
            _stub_healthy_dynamo(mock_boto)
            _stub_healthy_sqs(mock_boto)
            resp = await ctx.client.get("/admin/api/health")
        assert "checked_at" in resp.json()


class TestHealthDynamoDown:
    async def test_dynamo_failure_yields_degraded(self, ctx: AdminCtx) -> None:
        with patch("admin.routers.health.aioboto3") as mock_boto:
            _stub_failing_dynamo(mock_boto)
            _stub_healthy_sqs(mock_boto)
            resp = await ctx.client.get("/admin/api/health")
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["dynamodb"] == "unavailable"
        assert data["redis"] == "ok"  # Redis failure is independent

    async def test_dynamo_down_does_not_crash_endpoint(self, ctx: AdminCtx) -> None:
        with patch("admin.routers.health.aioboto3") as mock_boto:
            _stub_failing_dynamo(mock_boto)
            _stub_healthy_sqs(mock_boto)
            resp = await ctx.client.get("/admin/api/health")
        assert resp.status_code == 200  # Always 200; payload conveys health


class TestHealthRedisDown:
    async def test_redis_failure_yields_degraded(self, ctx: AdminCtx) -> None:
        ctx.redis.health = AsyncMock(return_value="unavailable")
        with patch("admin.routers.health.aioboto3") as mock_boto:
            _stub_healthy_dynamo(mock_boto)
            _stub_healthy_sqs(mock_boto)
            resp = await ctx.client.get("/admin/api/health")
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["redis"] == "unavailable"

    async def test_dynamo_ok_even_when_redis_down(self, ctx: AdminCtx) -> None:
        ctx.redis.health = AsyncMock(return_value="unavailable")
        with patch("admin.routers.health.aioboto3") as mock_boto:
            _stub_healthy_dynamo(mock_boto)
            _stub_healthy_sqs(mock_boto)
            resp = await ctx.client.get("/admin/api/health")
        assert resp.json()["dynamodb"] == "ok"


class TestHealthSqsNotConfigured:
    async def test_empty_sqs_url_reports_not_configured(self, ctx: AdminCtx) -> None:
        # Default config has sqs_escalation_url="" so SQS is not probed
        with patch("admin.routers.health.aioboto3") as mock_boto:
            _stub_healthy_dynamo(mock_boto)
            resp = await ctx.client.get("/admin/api/health")
        assert resp.json()["sqs"] == "not_configured"


# ---------------------------------------------------------------------------
# Helpers — stub aioboto3 async context managers
# ---------------------------------------------------------------------------

def _stub_healthy_dynamo(mock_boto: MagicMock) -> None:
    mock_ddb = AsyncMock()
    mock_ddb.describe_table = AsyncMock(return_value={"Table": {"TableStatus": "ACTIVE"}})
    mock_session = MagicMock()
    mock_session.client.return_value.__aenter__ = AsyncMock(return_value=mock_ddb)
    mock_session.client.return_value.__aexit__ = AsyncMock(return_value=False)
    mock_boto.Session.return_value = mock_session


def _stub_failing_dynamo(mock_boto: MagicMock) -> None:
    mock_session = MagicMock()
    failing_client = AsyncMock()
    failing_client.scan = AsyncMock(side_effect=Exception("ResourceNotFoundException"))
    mock_session.client.return_value.__aenter__ = AsyncMock(return_value=failing_client)
    mock_session.client.return_value.__aexit__ = AsyncMock(return_value=False)
    mock_boto.Session.return_value = mock_session


def _stub_healthy_sqs(mock_boto: MagicMock) -> None:
    # SQS is not checked when url is empty (the default); this helper exists
    # for future tests with a configured URL.
    pass
