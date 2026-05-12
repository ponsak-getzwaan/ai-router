# ---------------------------------------------------------------------------
# DynamoDB tables
#   - routing_rules: intent → vendor mapping (read by Strategist)
#   - audit_log:     per-request audit records (entity types, vendor, latency)
#   - review_log:    escalated messages pending human review
# ---------------------------------------------------------------------------

resource "aws_dynamodb_table" "routing_rules" {
  name         = "${var.project}-routing-rules"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "intent"

  attribute {
    name = "intent"
    type = "S"
  }
}

resource "aws_dynamodb_table" "audit_log" {
  name         = "${var.project}-audit-log"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "correlation_id"
  range_key    = "timestamp"

  attribute {
    name = "correlation_id"
    type = "S"
  }

  attribute {
    name = "timestamp"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }
}

resource "aws_dynamodb_table" "review_log" {
  name         = "${var.project}-review-log"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "correlation_id"

  attribute {
    name = "correlation_id"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }
}
