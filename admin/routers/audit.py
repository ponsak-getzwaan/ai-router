"""GET /admin/audit — query the audit log.

Returns entity type counts, vendor used, latency per correlation_id.
Never returns message text (raw or redacted). See architecture.md §end-to-end,
step 10: "NEVER values. NEVER raw message."
"""

from __future__ import annotations

import base64
import json
from typing import Any, cast

from fastapi import APIRouter, Query, Request

from admin.models import AuditQuery
from admin.services.dynamo_admin import DynamoAdminService

router = APIRouter(prefix="/admin/api/audit", tags=["audit"])


def _svc(request: Request) -> DynamoAdminService:
    return cast(DynamoAdminService, request.app.state.dynamo)


def _decode_cursor(cursor: str | None) -> dict[str, Any] | None:
    if not cursor:
        return None
    try:
        return cast(dict[str, Any], json.loads(base64.b64decode(cursor).decode()))
    except Exception:
        return None


@router.get("", response_model=AuditQuery)
async def query_audit(
    request: Request,
    correlation_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, description="Base64-encoded LastEvaluatedKey for pagination"),
) -> AuditQuery:
    return await _svc(request).query_audit(
        correlation_id=correlation_id,
        limit=limit,
        last_key=_decode_cursor(cursor),
    )
