"""Seed the DynamoDB routing rules table with default intent→vendor mappings.

Run once after infrastructure is created:
    uv run python scripts/seed_routing_rules.py

The routing rules can later be updated via the admin dashboard without redeployment.
"""

from __future__ import annotations

import boto3

TABLE = "ai-router-routing-rules"
REGION = "ap-southeast-1"

_SONNET = "apac.anthropic.claude-3-5-sonnet-20241022-v2:0"
_HAIKU  = "apac.anthropic.claude-3-haiku-20240307-v1:0"

RULES = [
    {
        "intent": "general_qa",
        "vendor": _SONNET,
        "fallback": _HAIKU,
        "description": "General questions and explanations",
    },
    {
        "intent": "code_assistance",
        "vendor": _SONNET,
        "fallback": _HAIKU,
        "description": "Coding, debugging, programming help",
    },
    {
        "intent": "simple_transactional",
        "vendor": _HAIKU,
        "fallback": _HAIKU,
        "description": "Quick lookups, prices, hours — Haiku is cheaper and fast enough",
    },
    {
        "intent": "ambiguous",
        "vendor": "escalate",
        "description": "Intent cannot be determined — escalate to human review by default",
    },
    {
        "intent": "out_of_scope",
        "vendor": "escalate",
        "description": "Request outside system scope — escalate to human review by default",
    },
]


def main() -> None:
    dynamo = boto3.resource("dynamodb", region_name=REGION)
    table = dynamo.Table(TABLE)

    with table.batch_writer() as batch:
        for rule in RULES:
            batch.put_item(Item=rule)
            print(f"  seeded: {rule['intent']} -> {rule['vendor']}")

    print(f"\nSeeded {len(RULES)} routing rules into {TABLE}.")


if __name__ == "__main__":
    main()
