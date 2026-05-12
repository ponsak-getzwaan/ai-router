"""Seed the DynamoDB routing rules table with default intent→vendor mappings.

Run once after infrastructure is created:
    uv run python scripts/seed_routing_rules.py

The routing rules can later be updated via the admin dashboard without redeployment.
"""

from __future__ import annotations

import boto3

TABLE = "ai-router-routing-rules"
REGION = "ap-southeast-1"

RULES = [
    {
        "intent": "general_qa",
        "vendor": "apac.anthropic.claude-sonnet-4-6-20241022-v2:0",
        "fallback": "apac.anthropic.claude-haiku-4-5-20241022-v1:0",
        "description": "General questions and explanations",
    },
    {
        "intent": "code_assistance",
        "vendor": "apac.anthropic.claude-sonnet-4-6-20241022-v2:0",
        "fallback": "apac.anthropic.claude-sonnet-4-6-20241022-v2:0",
        "description": "Coding, debugging, programming help",
    },
    {
        "intent": "simple_transactional",
        "vendor": "apac.anthropic.claude-haiku-4-5-20241022-v1:0",
        "fallback": "apac.anthropic.claude-haiku-4-5-20241022-v1:0",
        "description": "Quick lookups, prices, hours — Haiku is cheaper and fast enough",
    },
    {
        "intent": "ambiguous",
        "vendor": "apac.anthropic.claude-sonnet-4-6-20241022-v2:0",
        "fallback": "apac.anthropic.claude-sonnet-4-6-20241022-v2:0",
        "description": "Ambiguous intent — use Sonnet for best chance of a useful response",
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
