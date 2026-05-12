"""DynamoDB operations for routing rules and audit log.

Write surface: routing rules only (PUT /admin/routing-rules/{intent}).
Read surface: routing rules + audit log.
DeleteItem is denied by IAM — soft deletes only (not implemented; rules are overwritten).
"""

from __future__ import annotations

from typing import Any

import aioboto3  # type: ignore[import-untyped]
from boto3.dynamodb.conditions import Key  # type: ignore[import-untyped]

from admin.models import AuditQuery, AuditRecord, RoutingRule, RoutingRuleUpdate
from shared.logging import safe_log


class DynamoAdminService:
    def __init__(
        self,
        routing_table: str,
        audit_table: str,
        region: str,
    ) -> None:
        self._routing = routing_table
        self._audit = audit_table
        self._region = region
        self._session: aioboto3.Session = aioboto3.Session()

    # ------------------------------------------------------------------
    # Routing rules
    # ------------------------------------------------------------------

    async def list_routing_rules(self) -> list[RoutingRule]:
        try:
            async with self._session.resource("dynamodb", region_name=self._region) as dynamo:
                table = await dynamo.Table(self._routing)
                resp = await table.scan()
            return [self._parse_rule(item) for item in resp.get("Items", [])]
        except Exception as exc:
            safe_log.warning("admin.dynamo.rules_list_error", error_type=type(exc).__name__)
            return []

    async def get_routing_rule(self, intent: str) -> RoutingRule | None:
        try:
            async with self._session.resource("dynamodb", region_name=self._region) as dynamo:
                table = await dynamo.Table(self._routing)
                resp = await table.get_item(Key={"intent": intent})
            item = resp.get("Item")
            return self._parse_rule(item) if item else None
        except Exception as exc:
            safe_log.warning("admin.dynamo.rule_get_error", error_type=type(exc).__name__)
            return None

    async def put_routing_rule(self, intent: str, update: RoutingRuleUpdate) -> RoutingRule:
        item: dict[str, Any] = {
            "intent": intent,
            "vendor": update.vendor,
        }
        if update.fallback is not None:
            item["fallback"] = update.fallback
        if update.description is not None:
            item["description"] = update.description

        async with self._session.resource("dynamodb", region_name=self._region) as dynamo:
            table = await dynamo.Table(self._routing)
            await table.put_item(Item=item)

        safe_log.info("admin.routing_rule.updated", intent=intent, vendor=update.vendor)
        return self._parse_rule(item)

    @staticmethod
    def _parse_rule(item: dict[str, Any]) -> RoutingRule:
        return RoutingRule(
            intent=item["intent"],
            vendor=item["vendor"],
            fallback=item.get("fallback"),
            description=item.get("description"),
        )

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------

    async def query_audit(
        self,
        correlation_id: str | None = None,
        limit: int = 50,
        last_key: dict[str, Any] | None = None,
    ) -> AuditQuery:
        """Query the audit log.

        Returns entity types and counts only — never message content.
        """
        try:
            async with self._session.resource("dynamodb", region_name=self._region) as dynamo:
                table = await dynamo.Table(self._audit)

                kwargs: dict[str, Any] = {"Limit": min(limit, 100)}
                if last_key:
                    kwargs["ExclusiveStartKey"] = last_key

                if correlation_id:
                    resp = await table.query(
                        KeyConditionExpression=Key("correlation_id").eq(correlation_id),
                        **kwargs,
                    )
                else:
                    resp = await table.scan(**kwargs)

            records = [self._parse_audit(item) for item in resp.get("Items", [])]
            return AuditQuery(
                records=records,
                count=len(records),
                last_evaluated_key=resp.get("LastEvaluatedKey"),
            )
        except Exception as exc:
            safe_log.warning("admin.dynamo.audit_error", error_type=type(exc).__name__)
            return AuditQuery(records=[], count=0, last_evaluated_key=None)

    @staticmethod
    def _parse_audit(item: dict[str, Any]) -> AuditRecord:
        return AuditRecord(
            correlation_id=item.get("correlation_id", ""),
            timestamp=item.get("timestamp", ""),
            user_sub=item.get("user_sub", ""),
            session_id=item.get("session_id", ""),
            entity_types_redacted=item.get("entity_types_redacted", []),
            entity_count=int(item.get("entity_count", 0)),
            was_redacted=bool(item.get("was_redacted", False)),
            bouncer_allowed=item.get("bouncer_allowed"),
            bouncer_escalated=item.get("bouncer_escalated"),
            intent=item.get("intent"),
            intent_confidence=item.get("intent_confidence"),
            vendor=item.get("vendor"),
            routing_path=item.get("routing_path"),
            policy_blocked=item.get("policy_blocked"),
            total_latency_ms=item.get("total_latency_ms"),
            error_type=item.get("error_type"),
        )
