# ---------------------------------------------------------------------------
# ECR repositories — one per ECS service image
# ---------------------------------------------------------------------------

locals {
  ecr_repos = [
    "orchestrator",
    "bouncer",
    "classifier",
    "strategist",
    "adapters",
    "presidio-sidecar",
    "admin",
  ]
}

resource "aws_ecr_repository" "services" {
  for_each             = toset(local.ecr_repos)
  name                 = "${var.project}/${each.key}"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "services" {
  for_each   = aws_ecr_repository.services
  repository = each.value.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 10 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}
