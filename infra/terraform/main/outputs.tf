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

output "admin_spa_bucket" {
  description = "S3 bucket name for the admin SPA — used by the deploy script."
  value       = aws_s3_bucket.admin_spa.bucket
}

output "admin_spa_cloudfront_url" {
  description = "Admin dashboard URL (CloudFront distribution domain)."
  value       = "https://${aws_cloudfront_distribution.admin_spa.domain_name}"
}

output "admin_spa_cloudfront_id" {
  description = "CloudFront distribution ID — needed to invalidate cache after deploy."
  value       = aws_cloudfront_distribution.admin_spa.id
}

output "cognito_domain" {
  description = "Cognito hosted UI domain (used as VITE_COGNITO_DOMAIN)."
  value       = "https://${aws_cognito_user_pool_domain.admin.domain}.auth.${var.aws_region}.amazoncognito.com"
}

output "cognito_client_id" {
  description = "Cognito App Client ID (used as VITE_COGNITO_CLIENT_ID)."
  value       = aws_cognito_user_pool_client.admin_spa.id
}

output "cognito_user_pool_id" {
  description = "Cognito User Pool ID — for creating admin users with the CLI."
  value       = aws_cognito_user_pool.admin.id
}
