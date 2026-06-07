# ---------------------------------------------------------------------------
# VPC Endpoints
#
# ECS tasks in private subnets currently reach AWS APIs by going:
#   private subnet → NAT gateway → internet → AWS endpoint
# Each new TLS connection to Bedrock over this path costs ~1.7 s.
#
# Interface Endpoints route those calls through the AWS private network:
#   private subnet → ENI in same AZ → AWS service
# New-connection TLS overhead drops to <50 ms; warm connections faster still.
#
# Cost estimate (ap-southeast-1, 3 AZs):
#   bedrock-runtime  $0.01/hr × 3 AZs = ~$22/month + $0.01/GB data
#   sqs              $0.01/hr × 3 AZs = ~$22/month + $0.01/GB data
#   logs             $0.01/hr × 3 AZs = ~$22/month + $0.01/GB data
#   dynamodb         free (Gateway Endpoint)
#   s3               free (Gateway Endpoint)
#
# NAT gateway is kept — still needed for package downloads, external APIs.
# ---------------------------------------------------------------------------

resource "aws_security_group" "vpc_endpoints" {
  name        = "${var.project}-vpc-endpoints"
  description = "VPC Interface Endpoints - allow HTTPS inbound from ECS tasks"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "HTTPS from ECS tasks"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_tasks.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ---------------------------------------------------------------------------
# Bedrock Runtime — the primary latency fix
#
# private_dns_enabled = true means bedrock-runtime.ap-southeast-1.amazonaws.com
# resolves to the ENI private IP. No application code changes needed.
# Applies to both apac.* and global.* inference profile calls — the VPC
# endpoint handles the first hop; internal cross-region routing is unchanged.
# ---------------------------------------------------------------------------

resource "aws_vpc_endpoint" "bedrock_runtime" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.bedrock-runtime"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpc_endpoints.id]

  tags = {
    Name = "${var.project}-bedrock-runtime"
  }
}

# ---------------------------------------------------------------------------
# SQS — orchestrator ingests and escalation queue sends stay private
# ---------------------------------------------------------------------------

resource "aws_vpc_endpoint" "sqs" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.sqs"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpc_endpoints.id]

  tags = {
    Name = "${var.project}-sqs"
  }
}

# ---------------------------------------------------------------------------
# CloudWatch Logs — ECS task log delivery (no data leaves VPC)
# ---------------------------------------------------------------------------

resource "aws_vpc_endpoint" "logs" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.logs"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpc_endpoints.id]

  tags = {
    Name = "${var.project}-logs"
  }
}

# ---------------------------------------------------------------------------
# DynamoDB — free Gateway Endpoint (no per-AZ ENI cost)
# Used by orchestrator, admin, and pipeline services for routing rules,
# audit log, and review queue tables.
# ---------------------------------------------------------------------------

resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.aws_region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]

  tags = {
    Name = "${var.project}-dynamodb"
  }
}

# ---------------------------------------------------------------------------
# S3 — free Gateway Endpoint
# Required for ECS Fargate to pull ECR image layers (stored in S3) without
# going through the NAT gateway. Also used by CloudWatch Logs delivery.
# ---------------------------------------------------------------------------

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]

  tags = {
    Name = "${var.project}-s3"
  }
}
