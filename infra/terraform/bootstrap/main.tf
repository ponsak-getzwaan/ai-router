# Bootstrap: creates the S3 bucket + DynamoDB table used as the Terraform
# remote state backend for all subsequent infra work.
#
# Run ONCE, manually, before any other Terraform:
#   cd infra/terraform/bootstrap
#   terraform init
#   terraform apply
#
# After apply, copy the outputs into infra/terraform/main/backend.tf.
# Never run this again — the bucket and table are long-lived.

terraform {
  required_version = ">= 1.7"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.50"
    }
  }
  # Bootstrap has NO remote backend — it manages its own state locally.
  # Keep bootstrap/terraform.tfstate in a safe place (or commit it).
}

provider "aws" {
  region = "ap-southeast-1"

  default_tags {
    tags = {
      Project     = "ai-router"
      ManagedBy   = "terraform"
      Environment = var.environment
    }
  }
}

variable "environment" {
  type        = string
  default     = "prod"
  description = "Deployment environment tag (prod / staging)."
}

variable "project" {
  type        = string
  default     = "ai-router"
  description = "Project slug — used as a prefix on all resource names."
}

# ---------------------------------------------------------------------------
# S3 bucket for Terraform state
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "tfstate" {
  bucket = "${var.project}-tfstate-${data.aws_caller_identity.current.account_id}"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket                  = aws_s3_bucket.tfstate.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ---------------------------------------------------------------------------
# DynamoDB table for state locking
# ---------------------------------------------------------------------------

resource "aws_dynamodb_table" "tflock" {
  name         = "${var.project}-tflock"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  lifecycle {
    prevent_destroy = true
  }
}

# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------

data "aws_caller_identity" "current" {}

# ---------------------------------------------------------------------------
# Outputs — paste these into infra/terraform/main/backend.tf after apply
# ---------------------------------------------------------------------------

output "tfstate_bucket" {
  value       = aws_s3_bucket.tfstate.id
  description = "S3 bucket name for Terraform state. Use as 'bucket' in backend config."
}

output "tflock_table" {
  value       = aws_dynamodb_table.tflock.name
  description = "DynamoDB table name for state locking. Use as 'dynamodb_table' in backend config."
}

output "backend_config_snippet" {
  value = <<-EOT
    # Paste into infra/terraform/main/backend.tf
    terraform {
      backend "s3" {
        bucket         = "${aws_s3_bucket.tfstate.id}"
        key            = "ai-router/prod/terraform.tfstate"
        region         = "ap-southeast-1"
        dynamodb_table = "${aws_dynamodb_table.tflock.name}"
        encrypt        = true
      }
    }
  EOT
}
