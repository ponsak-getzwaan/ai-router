# ---------------------------------------------------------------------------
# AWS Cloud Map — VPC-internal service discovery
# Presidio is registered here so the Orchestrator can reach it via
# http://presidio.ai-router.internal:8080 (CLAUDE.md §7 Redactor).
# ---------------------------------------------------------------------------

resource "aws_service_discovery_private_dns_namespace" "main" {
  name        = "${var.project}.internal"
  description = "VPC-internal service discovery for ${var.project}"
  vpc         = aws_vpc.main.id
}

resource "aws_service_discovery_service" "presidio" {
  name = "presidio"

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.main.id
    dns_records {
      ttl  = 10
      type = "A"
    }
    routing_policy = "MULTIVALUE"
  }

  health_check_custom_config {
    failure_threshold = 1
  }
}
