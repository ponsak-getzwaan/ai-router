# ---------------------------------------------------------------------------
# Cognito User Pool — admin dashboard authentication
# ---------------------------------------------------------------------------

locals {
  cf_origin = "https://${aws_cloudfront_distribution.admin_spa.domain_name}"
}

resource "aws_cognito_user_pool" "admin" {
  name = "${var.project}-admin"

  # Email as username
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  password_policy {
    minimum_length                   = 12
    require_uppercase                = true
    require_lowercase                = true
    require_numbers                  = true
    require_symbols                  = false
    temporary_password_validity_days = 7
  }

  # Self-registration disabled — admin users are created by operators only
  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }
}

# Cognito hosted UI domain (prefix must be globally unique)
resource "aws_cognito_user_pool_domain" "admin" {
  domain       = "${var.project}-admin-${data.aws_caller_identity.current.account_id}"
  user_pool_id = aws_cognito_user_pool.admin.id
}

# App client — public client (no secret), PKCE required
resource "aws_cognito_user_pool_client" "admin_spa" {
  name         = "${var.project}-admin-spa"
  user_pool_id = aws_cognito_user_pool.admin.id

  # Public client: no secret
  generate_secret = false

  # PKCE + Authorization Code flow only
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  allowed_oauth_flows_user_pool_client = true
  supported_identity_providers         = ["COGNITO"]

  callback_urls = [
    "${local.cf_origin}/auth/callback",
    "http://localhost:5173/auth/callback",
  ]

  logout_urls = [
    local.cf_origin,
    "http://localhost:5173",
  ]

  # Token validity
  access_token_validity  = 1   # hours
  id_token_validity      = 1   # hours
  refresh_token_validity = 30  # days

  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }

  # Prevent user existence errors leaking
  prevent_user_existence_errors = "ENABLED"

  explicit_auth_flows = [
    "ALLOW_REFRESH_TOKEN_AUTH",
    "ALLOW_USER_SRP_AUTH",
  ]
}
