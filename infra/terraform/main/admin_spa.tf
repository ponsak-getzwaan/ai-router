# ---------------------------------------------------------------------------
# Admin SPA — S3 + CloudFront (OAC, no custom domain)
# ---------------------------------------------------------------------------

locals {
  spa_bucket_name = "${var.project}-admin-spa-${data.aws_caller_identity.current.account_id}"
}

# S3 bucket — private, public access fully blocked
resource "aws_s3_bucket" "admin_spa" {
  bucket = local.spa_bucket_name
}

resource "aws_s3_bucket_public_access_block" "admin_spa" {
  bucket = aws_s3_bucket.admin_spa.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "admin_spa" {
  bucket = aws_s3_bucket.admin_spa.id
  versioning_configuration {
    status = "Enabled"
  }
}

# CloudFront Origin Access Control (OAC) — replaces legacy OAI
resource "aws_cloudfront_origin_access_control" "admin_spa" {
  name                              = "${var.project}-admin-spa-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# S3 bucket policy — allow only the CloudFront OAC principal
data "aws_iam_policy_document" "admin_spa_bucket" {
  statement {
    sid    = "AllowCloudFrontOAC"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.admin_spa.arn}/*"]

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.admin_spa.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "admin_spa" {
  bucket = aws_s3_bucket.admin_spa.id
  policy = data.aws_iam_policy_document.admin_spa_bucket.json

  # Policy references the distribution ARN; distribution must exist first
  depends_on = [aws_cloudfront_distribution.admin_spa]
}

# CloudFront distribution
resource "aws_cloudfront_distribution" "admin_spa" {
  enabled             = true
  default_root_object = "index.html"
  price_class         = "PriceClass_All"
  comment             = "${var.project} admin SPA"

  origin {
    domain_name              = aws_s3_bucket.admin_spa.bucket_regional_domain_name
    origin_id                = "s3-admin-spa"
    origin_access_control_id = aws_cloudfront_origin_access_control.admin_spa.id
  }

  # ALB origin for /admin/* API calls
  origin {
    domain_name = aws_lb.admin.dns_name
    origin_id   = "alb-admin-api"

    custom_origin_config {
      http_port                = 80
      https_port               = 443
      origin_protocol_policy   = "http-only"
      origin_ssl_protocols     = ["TLSv1.2"]
      origin_read_timeout      = 60
      origin_keepalive_timeout = 60
    }
  }

  # Default cache behaviour — CachingDisabled so index.html always reflects latest deploy
  default_cache_behavior {
    target_origin_id       = "s3-admin-spa"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    # AWS managed CachingDisabled policy
    cache_policy_id = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
  }

  # /admin/api/* — API calls routed to ALB; no caching, all headers forwarded
  ordered_cache_behavior {
    path_pattern           = "/admin/api/*"
    target_origin_id       = "alb-admin-api"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods         = ["GET", "HEAD"]
    compress               = false

    # CachingDisabled — API responses must never be cached
    cache_policy_id = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"

    # AllViewerExceptHostHeader — forwards Authorization header and all other
    # request headers to the origin, but substitutes CloudFront's Host header
    # so the ALB receives its own hostname (required for ALB routing)
    origin_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac"
  }

  # assets/ — content-hashed filenames → long cache TTL via CachingOptimized
  ordered_cache_behavior {
    path_pattern           = "assets/*"
    target_origin_id       = "s3-admin-spa"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    # AWS managed CachingOptimized policy (default TTL 86400s, max 31536000s)
    cache_policy_id = "658327ea-f89d-4fab-a63d-7e88639e58f6"
  }

  # SPA fallback: S3 returns 403/404 for unknown paths → serve index.html
  custom_error_response {
    error_code            = 403
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 0
  }

  custom_error_response {
    error_code            = 404
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 0
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  # No custom domain — use the *.cloudfront.net certificate
  viewer_certificate {
    cloudfront_default_certificate = true
  }
}
