# ---------------------------------------------------------------------------
# ECS Fargate cluster + services (Phase 1: one service per logical layer)
#
# Images are referenced by ECR repo URI. On first deploy the repos will be
# empty — bootstrap them by pushing a placeholder image before running
# terraform apply. The deploy script (scripts/deploy.sh) handles this.
# ---------------------------------------------------------------------------

resource "aws_ecs_cluster" "main" {
  name = var.project

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${var.project}"
  retention_in_days = 30
}

locals {
  redis_url = "redis://${aws_elasticache_cluster.main.cache_nodes[0].address}:6379"

  # Common environment variables injected into every ECS task
  common_env = [
    { name = "AWS_REGION", value = var.aws_region },
    { name = "ENVIRONMENT", value = var.environment },
    { name = "REDIS_URL", value = local.redis_url },
  ]
}

# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

resource "aws_ecs_task_definition" "orchestrator" {
  family                   = "${var.project}-orchestrator"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.orchestrator_cpu
  memory                   = var.orchestrator_memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.orchestrator.arn

  container_definitions = jsonencode([{
    name      = "orchestrator"
    image     = "${aws_ecr_repository.services["orchestrator"].repository_url}:latest"
    essential = true
    environment = [
      { name = "ORCHESTRATOR_AWS_REGION", value = var.aws_region },
      { name = "ORCHESTRATOR_ENVIRONMENT", value = var.environment },
      { name = "ORCHESTRATOR_REDIS_URL", value = local.redis_url },
      { name = "ORCHESTRATOR_SQS_INCOMING_URL", value = aws_sqs_queue.incoming.url },
      { name = "ORCHESTRATOR_SQS_ESCALATION_URL", value = aws_sqs_queue.escalation.url },
      { name = "ORCHESTRATOR_DYNAMODB_AUDIT_TABLE", value = aws_dynamodb_table.audit_log.name },
      { name = "ORCHESTRATOR_DYNAMODB_REVIEW_TABLE", value = aws_dynamodb_table.review_log.name },
      { name = "ORCHESTRATOR_PRESIDIO_URL", value = "http://presidio.${var.project}.internal:8080" },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "orchestrator"
      }
    }
    portMappings = [{ containerPort = 8000, protocol = "tcp" }]
  }])
}

resource "aws_ecs_service" "orchestrator" {
  name            = "${var.project}-orchestrator"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.orchestrator.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  depends_on = [aws_iam_role_policy.orchestrator]
}

# ---------------------------------------------------------------------------
# Presidio sidecar
# ---------------------------------------------------------------------------

resource "aws_ecs_task_definition" "presidio" {
  family                   = "${var.project}-presidio"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.presidio_cpu
  memory                   = var.presidio_memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.pipeline_service.arn

  container_definitions = jsonencode([{
    name      = "presidio"
    image     = "${aws_ecr_repository.services["presidio-sidecar"].repository_url}:latest"
    essential = true
    environment = [
      { name = "AWS_REGION", value = var.aws_region },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "presidio"
      }
    }
    portMappings = [{ containerPort = 8080, protocol = "tcp" }]
    healthCheck = {
      command     = ["CMD-SHELL", "curl -f http://localhost:8080/health || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 60
    }
  }])
}

resource "aws_ecs_service" "presidio" {
  name            = "${var.project}-presidio"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.presidio.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  service_registries {
    registry_arn = aws_service_discovery_service.presidio.arn
  }
}

# ---------------------------------------------------------------------------
# Bouncer, Classifier, Strategist, Adapters — same pattern, different image
# ---------------------------------------------------------------------------

locals {
  pipeline_services = {
    bouncer    = { port = 8001 }
    classifier = { port = 8002 }
    strategist = { port = 8003 }
    adapters   = { port = 8004 }
  }
}

resource "aws_ecs_task_definition" "pipeline" {
  for_each                 = local.pipeline_services
  family                   = "${var.project}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.service_cpu
  memory                   = var.service_memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.pipeline_service.arn

  container_definitions = jsonencode([{
    name      = each.key
    image     = "${aws_ecr_repository.services[each.key].repository_url}:latest"
    essential = true
    environment = concat(local.common_env, [
      { name = "DYNAMODB_ROUTING_TABLE", value = aws_dynamodb_table.routing_rules.name },
    ])
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = each.key
      }
    }
    portMappings = [{ containerPort = each.value.port, protocol = "tcp" }]
  }])
}

resource "aws_ecs_service" "pipeline" {
  for_each        = local.pipeline_services
  name            = "${var.project}-${each.key}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.pipeline[each.key].arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  depends_on = [aws_iam_role_policy.pipeline_service]
}

# ---------------------------------------------------------------------------
# Admin dashboard
# ---------------------------------------------------------------------------

resource "aws_ecs_task_definition" "admin" {
  family                   = "${var.project}-admin"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.service_cpu
  memory                   = var.service_memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.admin.arn

  container_definitions = jsonencode([{
    name      = "admin"
    image     = "${aws_ecr_repository.services["admin"].repository_url}:latest"
    essential = true
    environment = [
      { name = "ADMIN_AWS_REGION", value = var.aws_region },
      { name = "ADMIN_ENVIRONMENT", value = var.environment },
      { name = "ADMIN_REDIS_URL", value = local.redis_url },
      { name = "ADMIN_SQS_ESCALATION_URL", value = aws_sqs_queue.escalation.url },
      { name = "ADMIN_DYNAMODB_ROUTING_TABLE", value = aws_dynamodb_table.routing_rules.name },
      { name = "ADMIN_DYNAMODB_AUDIT_TABLE", value = aws_dynamodb_table.audit_log.name },
      { name = "ADMIN_DYNAMODB_REVIEW_TABLE", value = aws_dynamodb_table.review_log.name },
      { name = "ADMIN_COGNITO_USER_POOL_ID", value = aws_cognito_user_pool.admin.id },
      { name = "ADMIN_COGNITO_REGION", value = var.aws_region },
      { name = "ADMIN_SQS_INCOMING_URL", value = aws_sqs_queue.incoming.url },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "admin"
      }
    }
    portMappings = [{ containerPort = 8000, protocol = "tcp" }]
  }])
}

resource "aws_ecs_service" "admin" {
  name            = "${var.project}-admin"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.admin.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.admin.arn
    container_name   = "admin"
    container_port   = 8000
  }

  depends_on = [aws_iam_role_policy.admin, aws_lb_listener.admin_http]
}
