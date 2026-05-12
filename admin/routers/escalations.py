"""Escalation queue management endpoints.

GET  /admin/escalations                 — list pending human-review messages
POST /admin/escalations/{id}/approve    — mark approved, delete from queue
POST /admin/escalations/{id}/reject     — mark rejected, delete from queue
POST /admin/escalations/{id}/requeue    — extend visibility=0 (back to queue)

Previews show only the redacted message. Vault tokens are never surfaced.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from admin.models import EscalationAction, EscalationList
from admin.services.sqs_admin import SQSAdminService

router = APIRouter(prefix="/admin/escalations", tags=["escalations"])


def _svc(request: Request) -> SQSAdminService:
    return request.app.state.sqs_admin


class _RequeueBody(BaseModel):
    receipt_handle: str
    annotation: str = Field(min_length=1, max_length=500)


class _ActionBody(BaseModel):
    receipt_handle: str = Field(min_length=1)


@router.get("", response_model=EscalationList)
async def list_escalations(
    request: Request,
    max_messages: int = Query(default=10, ge=1, le=10),
) -> EscalationList:
    return await _svc(request).list_pending(max_messages)


@router.post("/{correlation_id}/approve", response_model=EscalationAction)
async def approve_escalation(
    correlation_id: str,
    body: _ActionBody,
    request: Request,
) -> EscalationAction:
    result = await _svc(request).approve(body.receipt_handle, correlation_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Escalation not found")
    return result


@router.post("/{correlation_id}/reject", response_model=EscalationAction)
async def reject_escalation(
    correlation_id: str,
    body: _ActionBody,
    request: Request,
) -> EscalationAction:
    result = await _svc(request).reject(body.receipt_handle, correlation_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Escalation not found")
    return result


@router.post("/{correlation_id}/requeue", response_model=EscalationAction)
async def requeue_escalation(
    correlation_id: str,
    body: _RequeueBody,
    request: Request,
) -> EscalationAction:
    return await _svc(request).requeue(
        body.receipt_handle, correlation_id, body.annotation
    )
