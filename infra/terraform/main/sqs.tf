# ---------------------------------------------------------------------------
# SQS queues
#   - incoming:   API Gateway → Orchestrator
#   - escalation: layers → human review
#   - dlq:        dead-letter for both queues
# ---------------------------------------------------------------------------

resource "aws_sqs_queue" "dlq" {
  name                      = "${var.project}-dlq"
  message_retention_seconds = 1209600 # 14 days
}

resource "aws_sqs_queue" "incoming" {
  name                       = "${var.project}-incoming"
  visibility_timeout_seconds = 300
  message_retention_seconds  = 86400 # 1 day

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 3
  })
}

resource "aws_sqs_queue" "escalation" {
  name                       = "${var.project}-escalation"
  visibility_timeout_seconds = 300
  message_retention_seconds  = 604800 # 7 days

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 5
  })
}
