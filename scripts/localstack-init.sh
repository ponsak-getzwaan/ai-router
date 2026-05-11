#!/bin/bash
# LocalStack init script — runs once when LocalStack reports ready.
# Mounted to /etc/localstack/init/ready.d/init.sh by docker-compose.yml.
#
# Creates the SQS queues and DynamoDB tables the dev loop needs.
# See docs/architecture.md for the full set; this is the minimum for local dev.

set -euo pipefail

REGION="ap-southeast-1"
ENDPOINT="http://localhost:4566"

echo "[init] creating SQS queues..."

awslocal --region "$REGION" sqs create-queue \
  --queue-name "ai-router-incoming" \
  --attributes VisibilityTimeout=60,MessageRetentionPeriod=86400

awslocal --region "$REGION" sqs create-queue \
  --queue-name "ai-router-handoff" \
  --attributes VisibilityTimeout=300,MessageRetentionPeriod=1209600

awslocal --region "$REGION" sqs create-queue \
  --queue-name "ai-router-dlq" \
  --attributes MessageRetentionPeriod=1209600

echo "[init] creating DynamoDB tables..."

awslocal --region "$REGION" dynamodb create-table \
  --table-name "intent_taxonomy" \
  --attribute-definitions AttributeName=domain,AttributeType=S AttributeName=intent,AttributeType=S \
  --key-schema AttributeName=domain,KeyType=HASH AttributeName=intent,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST

awslocal --region "$REGION" dynamodb create-table \
  --table-name "routing_rules" \
  --attribute-definitions AttributeName=intent_key,AttributeType=S \
  --key-schema AttributeName=intent_key,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST

awslocal --region "$REGION" dynamodb create-table \
  --table-name "review_log" \
  --attribute-definitions AttributeName=correlation_id,AttributeType=S AttributeName=timestamp,AttributeType=S \
  --key-schema AttributeName=correlation_id,KeyType=HASH AttributeName=timestamp,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST

awslocal --region "$REGION" dynamodb create-table \
  --table-name "audit" \
  --attribute-definitions AttributeName=correlation_id,AttributeType=S \
  --key-schema AttributeName=correlation_id,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST

echo "[init] done."
