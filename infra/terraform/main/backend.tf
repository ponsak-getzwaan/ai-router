terraform {
  backend "s3" {
    bucket       = "ai-router-tfstate-026651348796"
    key          = "ai-router/prod/terraform.tfstate"
    region       = "ap-southeast-1"
    encrypt      = true
    use_lockfile = true
  }
}
