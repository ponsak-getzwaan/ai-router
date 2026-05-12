"""Routing rules CRUD.

GET /admin/routing-rules          — list all intent→vendor mappings
GET /admin/routing-rules/{intent} — get one rule
PUT /admin/routing-rules/{intent} — update one rule (takes effect immediately)

Changes to routing rules take effect on the next request — the strategist
reads DynamoDB at routing time with a short TTL cache.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from admin.models import RoutingRule, RoutingRuleUpdate
from admin.services.dynamo_admin import DynamoAdminService

router = APIRouter(prefix="/admin/routing-rules", tags=["routing-rules"])


def _svc(request: Request) -> DynamoAdminService:
    return request.app.state.dynamo


@router.get("", response_model=list[RoutingRule])
async def list_routing_rules(request: Request) -> list[RoutingRule]:
    return await _svc(request).list_routing_rules()


@router.get("/{intent}", response_model=RoutingRule)
async def get_routing_rule(intent: str, request: Request) -> RoutingRule:
    rule = await _svc(request).get_routing_rule(intent)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"No routing rule for intent '{intent}'")
    return rule


@router.put("/{intent}", response_model=RoutingRule)
async def put_routing_rule(
    intent: str,
    body: RoutingRuleUpdate,
    request: Request,
) -> RoutingRule:
    return await _svc(request).put_routing_rule(intent, body)
