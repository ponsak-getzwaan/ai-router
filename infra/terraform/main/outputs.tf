output "ecr_repos" {
  description = "ECR repository URLs keyed by service name."
  value       = { for k, v in aws_ecr_repository.services : k => v.repository_url }
}

output "sqs_incoming_url" {
  value = aws_sqs_queue.incoming.url
}

output "sqs_escalation_url" {
  value = aws_sqs_queue.escalation.url
}

output "redis_endpoint" {
  value = "${aws_elasticache_cluster.main.cache_nodes[0].address}:6379"
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "dynamodb_routing_table" {
  value = aws_dynamodb_table.routing_rules.name
}

output "dynamodb_audit_table" {
  value = aws_dynamodb_table.audit_log.name
}

output "vpc_id" {
  value = aws_vpc.main.id
}

output "private_subnet_ids" {
  value = aws_subnet.private[*].id
}
