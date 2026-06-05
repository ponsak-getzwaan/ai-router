# ---------------------------------------------------------------------------
# ALB for admin API — internet-facing, CloudFront-only ingress
# CloudFront → ALB (HTTP/80) → admin ECS tasks (HTTP/8000)
# ---------------------------------------------------------------------------

# Restrict ALB ingress to CloudFront origin-facing IP ranges only
data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

resource "aws_security_group" "admin_alb" {
  name        = "${var.project}-admin-alb"
  description = "Admin ALB - inbound HTTP from CloudFront origin IPs only"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    prefix_list_ids = [data.aws_ec2_managed_prefix_list.cloudfront.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_lb" "admin" {
  name               = "${var.project}-admin"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.admin_alb.id]
  subnets            = aws_subnet.public[*].id
  idle_timeout       = 60
}

resource "aws_lb_target_group" "admin" {
  name        = "${var.project}-admin"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id

  health_check {
    path                = "/health"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
    matcher             = "200"
  }

  deregistration_delay = 30
}

resource "aws_lb_listener" "admin_http" {
  load_balancer_arn = aws_lb.admin.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.admin.arn
  }
}
