terraform {
  backend "s3" {
    bucket       = "ai-router-tfstate-859287180127"
    key          = "ai-router/prod/terraform.tfstate"
    region       = "ap-southeast-1"
    encrypt      = true
    use_lockfile = true
  }
}
