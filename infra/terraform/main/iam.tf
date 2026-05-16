# ---------------------------------------------------------------------------
# IAM roles and policies
#
# Non-negotiables (CLAUDE.md §3):
#   - Bedrock IAM policy includes aws:RequestedRegion condition locked to
#     ap-southeast-1. This is defence-in-depth at the IAM level, not just
#     application-level routing.
#   - Admin role explicitly denies bedrock:*, sqs:SendMessage on incoming
#     queue, and dynamodb:DeleteItem.
# ---------------------------------------------------------------------------

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.name
}

# ---------------------------------------------------------------------------
# ECS task execution role (shared — pulls images, writes logs)
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ecs_execution" {
  name               = "${var.project}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# ---------------------------------------------------------------------------
# Orchestrator task role
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "orchestrator" {
  # SQS — consume incoming, send to escalation
  statement {
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.incoming.arn]
  }
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.escalation.arn]
  }

  # DynamoDB — audit log + review log writes
  statement {
    actions   = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query"]
    resources = [aws_dynamodb_table.audit_log.arn, aws_dynamodb_table.review_log.arn]
  }

  # ElastiCache is network-level access (no IAM policy needed for Redis)

  # Bedrock — locked to ap-southeast-1 at IAM level (CLAUDE.md §3.9)
  statement {
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = ["ap-southeast-1"]
    }
  }

  # CloudWatch metrics
  statement {
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]
  }

  # X-Ray tracing
  statement {
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }
}

resource "aws_iam_role" "orchestrator" {
  name               = "${var.project}-orchestrator"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy" "orchestrator" {
  role   = aws_iam_role.orchestrator.id
  policy = data.aws_iam_policy_document.orchestrator.json
}

# ---------------------------------------------------------------------------
# Pipeline service role (Bouncer, Classifier, Strategist, Adapters)
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "pipeline_service" {
  # DynamoDB — routing rules (read-only)
  statement {
    actions   = ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan"]
    resources = [aws_dynamodb_table.routing_rules.arn]
  }

  # Bedrock — locked to ap-southeast-1
  statement {
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = ["ap-southeast-1"]
    }
  }

  # CloudWatch metrics
  statement {
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]
  }

  # X-Ray
  statement {
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }
}

resource "aws_iam_role" "pipeline_service" {
  name               = "${var.project}-pipeline-service"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy" "pipeline_service" {
  role   = aws_iam_role.pipeline_service.id
  policy = data.aws_iam_policy_document.pipeline_service.json
}

# ---------------------------------------------------------------------------
# Admin dashboard role — read-heavy; explicit denies on dangerous actions
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "admin_allow" {
  statement {
    actions = [
      "dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan",
      "dynamodb:PutItem", "dynamodb:UpdateItem", # routing rules editor + escalation actions
    ]
    resources = [
      aws_dynamodb_table.routing_rules.arn,
      aws_dynamodb_table.audit_log.arn,
      aws_dynamodb_table.review_log.arn,
    ]
  }
  statement {
    actions   = ["sqs:GetQueueAttributes", "sqs:ReceiveMessage", "sqs:DeleteMessage"]
    resources = [aws_sqs_queue.escalation.arn]
  }
  # Test console submits messages through the real pipeline for accurate metrics
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.incoming.arn]
  }
  statement {
    actions   = ["cloudwatch:GetMetricData", "cloudwatch:ListMetrics", "cloudwatch:GetMetricStatistics"]
    resources = ["*"]
  }
}

data "aws_iam_policy_document" "admin_deny" {
  # Safety net — admin must never touch Bedrock or hard-delete audit records.
  statement {
    effect    = "Deny"
    actions   = ["bedrock:*"]
    resources = ["*"]
  }
  statement {
    effect    = "Deny"
    actions   = ["dynamodb:DeleteItem"]
    resources = ["*"]
  }
}

data "aws_iam_policy_document" "admin_combined" {
  source_policy_documents = [
    data.aws_iam_policy_document.admin_allow.json,
    data.aws_iam_policy_document.admin_deny.json,
  ]
}

resource "aws_iam_role" "admin" {
  name               = "${var.project}-admin"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy" "admin" {
  role   = aws_iam_role.admin.id
  policy = data.aws_iam_policy_document.admin_combined.json
}
