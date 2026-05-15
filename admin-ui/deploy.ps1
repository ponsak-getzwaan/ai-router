# deploy.ps1 — build and push the admin SPA to S3 + invalidate CloudFront
#
# Usage:
#   .\deploy.ps1
#
# Reads BUCKET and DISTRIBUTION_ID from Terraform outputs automatically.
# Run from the repo root or from admin-ui/.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$TfDir    = Join-Path $RepoRoot "infra\terraform\main"
$UiDir    = $PSScriptRoot

# --- Read Terraform outputs ---
Write-Host "Reading Terraform outputs..."
Push-Location $TfDir
$TfOutputs    = terraform output -json | ConvertFrom-Json
$Bucket       = $TfOutputs.admin_spa_bucket.value
$Distribution = $TfOutputs.admin_spa_cloudfront_id.value
$Url          = $TfOutputs.admin_spa_cloudfront_url.value
Pop-Location

Write-Host "Bucket:       $Bucket"
Write-Host "Distribution: $Distribution"
Write-Host "URL:          $Url"

# --- Build ---
Write-Host "`nBuilding admin UI..."
Push-Location $UiDir
npm run build
Pop-Location

# --- Sync to S3 ---
Write-Host "`nSyncing to S3..."
$DistDir = Join-Path $UiDir "dist"

# index.html — no cache (must always be fresh)
aws s3 cp "$DistDir\index.html" "s3://$Bucket/index.html" `
  --cache-control "no-cache, no-store, must-revalidate" `
  --content-type "text/html"

# assets/ — immutable long cache (content-hashed filenames)
aws s3 sync "$DistDir\assets" "s3://$Bucket/assets" `
  --cache-control "public, max-age=31536000, immutable" `
  --delete

# Everything else (favicon, manifest, etc.)
aws s3 sync $DistDir "s3://$Bucket" `
  --exclude "index.html" `
  --exclude "assets/*" `
  --delete

# --- Invalidate CloudFront ---
Write-Host "`nInvalidating CloudFront cache..."
aws cloudfront create-invalidation `
  --distribution-id $Distribution `
  --paths "/*" `
  | Out-Null

Write-Host "`nDone. Admin dashboard: $Url"
