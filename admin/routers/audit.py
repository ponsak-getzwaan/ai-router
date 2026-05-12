"""GET /admin/audit — query the audit log.

Returns entity type counts, vendor used, latency per correlation_id.
Never returns message text (raw or redacted). See architecture.md §end-to-end,
step 10: "NEVER values. NEVER raw message."
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from admin.models import AuditQuery
from admin.services.dynamo_admin import DynamoAdminService

router = APIRouter(prefix="/admin/audit", tags=["audit"])


def _svc(request: Request) -> DynamoAdminService:
    return request.app.state.dynamo


@router.get("", response_model=AuditQuery)
async def query_audit(
    request: Request,
    correlation_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
) -> AuditQuery:
    return await _svc(request).query_audit(
        correlation_id=correlation_id,
        limit=limit,
    )
