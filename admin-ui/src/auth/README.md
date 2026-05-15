# Admin UI — Auth Setup (Local Dev)

## Prerequisite: a Cognito dev User Pool

Create a dedicated pool for local development in the sandbox account:

```bash
# Terraform — add to infra/terraform/cognito.tf
resource "aws_cognito_user_pool" "admin_dev" {
  name = "airouter-admin-dev"
  # ... same settings as prod pool
}

resource "aws_cognito_user_pool_client" "admin_dev_spa" {
  name                                 = "admin-spa-dev"
  user_pool_id                         = aws_cognito_user_pool.admin_dev.id
  generate_secret                      = false   # SPAs cannot keep secrets
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "aws.cognito.signin.user.admin"]
  allowed_oauth_flows_user_pool_client = true
  callback_urls                        = ["http://localhost:5173/auth/callback"]
  logout_urls                          = ["http://localhost:5173/"]
  supported_identity_providers         = ["COGNITO"]
}
```

After applying, create a test user:

```bash
aws cognito-idp admin-create-user \
  --user-pool-id <pool-id> \
  --username admin@example.com \
  --temporary-password Temp1234! \
  --region ap-southeast-1
```

## Configure .env.local

Copy `.env.example` to `.env.local` and fill in:

- `VITE_COGNITO_DOMAIN` — the Hosted UI domain, e.g. `https://airouter-admin-dev.auth.ap-southeast-1.amazoncognito.com`
- `VITE_COGNITO_CLIENT_ID` — the app client ID from the console or Terraform output
- Leave redirect/logout URIs as-is for local dev

## Start the dev server

```bash
cd admin-ui
pnpm install
pnpm dev
```

Open http://localhost:5173 — it redirects to Cognito, you log in, and you land on the Pipeline Health view.

## First login

Cognito forces a password change on first login for admin-created users. Set a permanent password from the console:

```bash
aws cognito-idp admin-set-user-password \
  --user-pool-id <pool-id> \
  --username admin@example.com \
  --password AdminPass123! \
  --permanent \
  --region ap-southeast-1
```
