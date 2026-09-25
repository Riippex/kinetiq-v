data "aws_region" "current" {}

# Existing public hosted zone for domain_name. Terraform does not create the
# zone itself (that requires manual registrar NS delegation outside
# Terraform's blast radius) -- it must already exist in this account.
# domain_name is a required variable (see variables.tf): the hackathon
# environment must have exactly one real, usable HTTPS public origin before
# it is considered deployable, so there is no "unset" case to guard here.
data "aws_route53_zone" "public" {
  name         = var.domain_name
  private_zone = false
}

# ECS Cluster
resource "aws_ecs_cluster" "main" {
  name = "${var.project}-${var.environment}-cluster"

  setting {
    name  = "containerInsights"
    value = "disabled" # Disabled to avoid extra CloudWatch metric costs in hackathon
  }

  tags = {
    Name        = "${var.project}-${var.environment}-cluster"
    Environment = var.environment
    Project     = var.project
  }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name = aws_ecs_cluster.main.name

  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    capacity_provider = var.use_fargate_spot ? "FARGATE_SPOT" : "FARGATE"
    weight            = 100
    base              = 0
  }
}

# Application Load Balancer
resource "aws_lb" "main" {
  name               = "${var.project}-${var.environment}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [var.alb_security_group_id]
  subnets            = var.public_subnet_ids

  enable_deletion_protection = false

  # Hard stop, not just a convention: the hackathon deployment must have
  # one real, usable HTTPS public origin before it is considered
  # deployable (var.domain_name has no default -- Terraform already
  # refuses to plan without it -- and certificate_arn's own validation
  # requires domain_name whenever it is set). This precondition is the
  # belt-and-suspenders check that the certificate actually resolved,
  # evaluated against known plan-time values so it never blocks on an
  # apply-time-only computed value.
  lifecycle {
    precondition {
      condition     = var.domain_name != "" && local.has_https
      error_message = "The hackathon environment requires one usable HTTPS public origin: domain_name must be a real, existing Route53-hosted domain, and a certificate (certificate_arn or Terraform's own DNS-validated one) must resolve for it. HTTP-only deployment is not supported -- see docs/runbooks/infrastructure-bootstrap.md."
    }
  }

  tags = {
    Name        = "${var.project}-${var.environment}-alb"
    Environment = var.environment
    Project     = var.project
  }
}

# Target Group: Backend (Django ASGI on port 8000)
resource "aws_lb_target_group" "backend" {
  name        = "${var.project}-${var.environment}-tg-backend"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = "/health/"
    protocol            = "HTTP"
    port                = "8000"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = {
    Name        = "${var.project}-${var.environment}-tg-backend"
    Environment = var.environment
    Project     = var.project
  }
}

# Target Group: Web (Next.js on port 3000)
resource "aws_lb_target_group" "web" {
  name        = "${var.project}-${var.environment}-tg-web"
  port        = 3000
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = "/"
    protocol            = "HTTP"
    port                = "3000"
    matcher             = "200-399"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = {
    Name        = "${var.project}-${var.environment}-tg-web"
    Environment = var.environment
    Project     = var.project
  }
}

# ACM certificate for domain_name, DNS-validated against its existing
# Route53 zone. Only requested when the caller did not already bring their
# own certificate_arn -- which, per its own variable validation, must be a
# certificate actually issued for exactly this domain_name.
resource "aws_acm_certificate" "main" {
  count             = var.certificate_arn == "" ? 1 : 0
  domain_name       = var.domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = {
    Name        = "${var.project}-${var.environment}-cert"
    Environment = var.environment
    Project     = var.project
  }
}

resource "aws_route53_record" "cert_validation" {
  for_each = var.certificate_arn == "" ? {
    for dvo in aws_acm_certificate.main[0].domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  } : {}

  zone_id         = data.aws_route53_zone.public.zone_id
  name            = each.value.name
  type            = each.value.type
  records         = [each.value.record]
  ttl             = 60
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "main" {
  count                   = var.certificate_arn == "" ? 1 : 0
  certificate_arn         = aws_acm_certificate.main[0].arn
  validation_record_fqdns = [for r in aws_route53_record.cert_validation : r.fqdn]
}

locals {
  # A pre-supplied certificate always wins (its variable validation already
  # requires domain_name to be set to the hostname it actually covers);
  # otherwise use the one this module DNS-validated for domain_name above.
  effective_certificate_arn = var.certificate_arn != "" ? var.certificate_arn : aws_acm_certificate_validation.main[0].certificate_arn
  has_https                 = local.effective_certificate_arn != ""

  # One canonical public origin. domain_name is a required variable and
  # certificate_arn (bring-your-own or auto-provisioned above) is always
  # coherent with it -- see the aws_lb.main precondition below for the hard
  # stop if that were ever somehow not true. The ALB's own AWS-generated
  # DNS name is never used as a public host: no certificate should ever be
  # issued for it, and advertising it over HTTPS would mean either serving
  # plain HTTP mislabeled as HTTPS or presenting a certificate for a
  # completely different hostname.
  public_host   = var.domain_name
  public_scheme = "https"
  public_origin = "${local.public_scheme}://${local.public_host}"
}

# HTTPS Listener -- unconditional: has_https is guaranteed true for any
# configuration that reaches this point (domain_name is required, and
# certificate_arn's own validation requires domain_name whenever it is
# set), so there is no longer an "HTTP-only" branch to build for.
resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = local.effective_certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}

# Next.js owns the same-origin GraphQL BFF and browser authentication
# endpoints. They must be evaluated before the broader backend /api/* rule
# below, or the ALB sends them straight to Django where they do not exist.
resource "aws_lb_listener_rule" "web_graphql_proxy_https" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 5

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }

  condition {
    path_pattern {
      values = ["/api/graphql", "/api/graphql/", "/api/auth/*"]
    }
  }
}

resource "aws_lb_listener_rule" "backend_routes_https" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.backend.arn
  }

  condition {
    path_pattern {
      values = ["/api/*", "/graphql*", "/health*", "/ws/*", "/mcp*"]
    }
  }
}

# HTTP Listener on port 80: always redirects to HTTPS. There is no longer a
# direct-forward branch -- the hackathon deployment does not have an
# HTTP-only mode (see the aws_lb.main precondition below), so every HTTP
# request either becomes HTTPS or is not served.
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"

    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

# Alias the canonical domain at the ALB.
resource "aws_route53_record" "alb_alias" {
  zone_id = data.aws_route53_zone.public.zone_id
  name    = var.domain_name
  type    = "A"

  alias {
    name                   = aws_lb.main.dns_name
    zone_id                = aws_lb.main.zone_id
    evaluate_target_health = true
  }
}

# ECS Task Definition: Backend
resource "aws_ecs_task_definition" "backend" {
  family                   = "${var.project}-backend-${var.environment}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = var.ecs_execution_role_arn
  task_role_arn            = var.backend_task_role_arn

  container_definitions = jsonencode([
    {
      name      = "backend"
      image     = var.backend_image
      essential = true

      portMappings = [
        {
          containerPort = 8000
          hostPort      = 8000
          protocol      = "tcp"
        }
      ]

      environment = [
        { name = "DJANGO_DEBUG", value = "false" },
        # Exact host(s) only -- never a wildcard: the ALB's own DNS name,
        # or the canonical domain once one is configured.
        { name = "DJANGO_ALLOWED_HOSTS", value = local.public_host },
        # MCP_ALLOWED_HOSTS is left unset: settings.py already derives it
        # from ALLOWED_HOSTS (each host plus its ":*" port variant) when not
        # explicitly provided, so fixing DJANGO_ALLOWED_HOSTS above already
        # makes it exact.
        { name = "AWS_REGION", value = data.aws_region.current.name },
        { name = "MEDIA_S3_BUCKET", value = var.media_bucket_id },
        { name = "DISPLAY_PAIRING_STORE", value = "redis" },
        { name = "COGNITO_ISSUER_URL", value = var.cognito_issuer_url },
        { name = "COGNITO_JWKS_URL", value = var.cognito_jwks_url },
        { name = "COGNITO_ALLOWED_CLIENT_IDS", value = "${var.cognito_web_client_id},${var.cognito_mobile_client_id}" },
        { name = "MCP_OIDC_ISSUER", value = var.cognito_issuer_url },
        { name = "MCP_OIDC_AUDIENCE", value = var.cognito_web_client_id },
        { name = "MCP_OIDC_JWKS_URL", value = var.cognito_jwks_url },
        { name = "MCP_OIDC_REQUIRED_SCOPE", value = "kinetiq/coach" },
        { name = "MCP_OIDC_TOKEN_USE", value = "access" },
        # Derived from the same canonical origin as everything else --
        # never hardcoded to https:// when no HTTPS listener/edge exists.
        { name = "MCP_RESOURCE_URL", value = "${local.public_origin}/mcp" }
      ]

      secrets = [
        {
          name      = "DJANGO_SECRET_KEY"
          valueFrom = var.django_secret_key_arn
        },
        {
          name      = "DATABASE_URL"
          valueFrom = "${var.database_secret_arn}:database_url::"
        },
        {
          name      = "REDIS_URL"
          valueFrom = "${var.redis_secret_arn}:redis_url::"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = "/ecs/${var.project}-backend-${var.environment}"
          "awslogs-region"        = data.aws_region.current.name
          "awslogs-stream-prefix" = "backend"
        }
      }
    }
  ])

  tags = {
    Name        = "${var.project}-backend-task"
    Environment = var.environment
    Project     = var.project
  }
}

# ECS Task Definition: Web (Next.js)
resource "aws_ecs_task_definition" "web" {
  family                   = "${var.project}-web-${var.environment}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = var.ecs_execution_role_arn

  container_definitions = jsonencode([
    {
      name      = "web"
      image     = var.web_image
      essential = true

      portMappings = [
        {
          containerPort = 3000
          hostPort      = 3000
          protocol      = "tcp"
        }
      ]

      environment = [
        { name = "NODE_ENV", value = "production" },
        { name = "PORT", value = "3000" },
        { name = "KINETIQ_PUBLIC_ORIGIN", value = local.public_origin },
        { name = "COGNITO_HOSTED_UI_DOMAIN", value = var.cognito_hosted_ui_domain },
        { name = "COGNITO_WEB_CLIENT_ID", value = var.cognito_web_client_id },
        # apps/web/src/app/api/graphql/route.ts reads KINETIQ_BACKEND_GRAPHQL_URL
        # server-side (a BFF proxy, never exposed to the browser) --
        # NEXT_PUBLIC_GRAPHQL_ENDPOINT is never read anywhere in the app and
        # was dead configuration. The ALB is reachable from the web task
        # (private-app subnet -> NAT -> internet -> internet-facing ALB).
        { name = "KINETIQ_BACKEND_GRAPHQL_URL", value = "${local.public_origin}/graphql/" }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = "/ecs/${var.project}-web-${var.environment}"
          "awslogs-region"        = data.aws_region.current.name
          "awslogs-stream-prefix" = "web"
        }
      }
    }
  ])

  tags = {
    Name        = "${var.project}-web-task"
    Environment = var.environment
    Project     = var.project
  }
}

# ECS Task Definition: Worker (Media cleanup & background tasks)
resource "aws_ecs_task_definition" "worker" {
  family                   = "${var.project}-worker-${var.environment}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = var.ecs_execution_role_arn
  task_role_arn            = var.worker_task_role_arn

  container_definitions = jsonencode([
    {
      name      = "worker"
      image     = var.backend_image
      essential = true
      command   = ["python", "manage.py", "process_media_cleanup"]

      environment = [
        { name = "DJANGO_DEBUG", value = "false" },
        { name = "AWS_REGION", value = data.aws_region.current.name },
        { name = "MEDIA_S3_BUCKET", value = var.media_bucket_id }
      ]

      secrets = [
        {
          name      = "DJANGO_SECRET_KEY"
          valueFrom = var.django_secret_key_arn
        },
        {
          name      = "DATABASE_URL"
          valueFrom = "${var.database_secret_arn}:database_url::"
        },
        {
          name      = "REDIS_URL"
          valueFrom = "${var.redis_secret_arn}:redis_url::"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = "/ecs/${var.project}-worker-${var.environment}"
          "awslogs-region"        = data.aws_region.current.name
          "awslogs-stream-prefix" = "worker"
        }
      }
    }
  ])

  tags = {
    Name        = "${var.project}-worker-task"
    Environment = var.environment
    Project     = var.project
  }
}

# ECS Task Definition: One-off Database Migration Task
resource "aws_ecs_task_definition" "migrate" {
  family                   = "${var.project}-migrate-${var.environment}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = var.ecs_execution_role_arn
  task_role_arn            = var.backend_task_role_arn

  container_definitions = jsonencode([
    {
      name      = "migrate"
      image     = var.backend_image
      essential = true
      command   = ["python", "manage.py", "migrate", "--noinput"]

      environment = [
        { name = "DJANGO_DEBUG", value = "false" },
        { name = "AWS_REGION", value = data.aws_region.current.name }
      ]

      secrets = [
        {
          name      = "DJANGO_SECRET_KEY"
          valueFrom = var.django_secret_key_arn
        },
        {
          name      = "DATABASE_URL"
          valueFrom = "${var.database_secret_arn}:database_url::"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = "/ecs/${var.project}-migrate-${var.environment}"
          "awslogs-region"        = data.aws_region.current.name
          "awslogs-stream-prefix" = "migrate"
        }
      }
    }
  ])

  tags = {
    Name        = "${var.project}-migrate-task"
    Environment = var.environment
    Project     = var.project
  }
}

# ECS Services
resource "aws_ecs_service" "backend" {
  name            = "${var.project}-backend-${var.environment}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.backend.arn
  desired_count   = var.bootstrap_mode ? 0 : 1

  capacity_provider_strategy {
    capacity_provider = var.use_fargate_spot ? "FARGATE_SPOT" : "FARGATE"
    weight            = 100
  }

  network_configuration {
    subnets          = var.private_app_subnet_ids
    security_groups  = [var.ecs_tasks_security_group_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.backend.arn
    container_name   = "backend"
    container_port   = 8000
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  # The deployment workflow registers immutable task definition revisions and
  # promotes the exact revision it just verified. Terraform continues to own
  # the service configuration, but must not roll that release pointer back to
  # the revision captured by the last infrastructure apply.
  lifecycle {
    ignore_changes = [task_definition]
  }

  depends_on = [aws_lb_listener.http]

  tags = {
    Name        = "${var.project}-backend-service"
    Environment = var.environment
    Project     = var.project
  }
}

resource "aws_ecs_service" "web" {
  name            = "${var.project}-web-${var.environment}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.web.arn
  desired_count   = var.bootstrap_mode ? 0 : 1

  capacity_provider_strategy {
    capacity_provider = var.use_fargate_spot ? "FARGATE_SPOT" : "FARGATE"
    weight            = 100
  }

  network_configuration {
    subnets          = var.private_app_subnet_ids
    security_groups  = [var.ecs_tasks_security_group_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.web.arn
    container_name   = "web"
    container_port   = 3000
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  # See the backend service: application releases own this pointer while
  # Terraform owns the surrounding service infrastructure.
  lifecycle {
    ignore_changes = [task_definition]
  }

  depends_on = [aws_lb_listener.http]

  tags = {
    Name        = "${var.project}-web-service"
    Environment = var.environment
    Project     = var.project
  }
}

# The media-cleanup command (`manage.py process_media_cleanup`) is a
# one-shot batch job: it processes whatever is currently due and exits 0.
# Running it as an `aws_ecs_service` (desired_count = 1, as before) means
# ECS perpetually relaunches it the instant it exits -- a permanent
# crash-restart loop, not a real long-running worker, generating constant
# CloudWatch Logs churn and Fargate billing for a task that is never
# actually "up". A scheduled ECS task (EventBridge Scheduler -> ecs:RunTask)
# is what a one-shot, periodically-due job actually is.
#
# Note: `messaging` provisions a real EventBridge bus + SQS consumer queue
# for the outbox-delivered domain events described in docs/architecture.md,
# but no application code publishes to it yet (MediaEventOutboxService's
# only wired publisher is a log-only stub) and no SQS-consuming command
# exists in services/backend. That queue is therefore idle infrastructure,
# not a currently-required long-running consumer -- implementing one is a
# separate, application-layer feature, not an infra correction.
resource "aws_scheduler_schedule" "media_cleanup" {
  name                         = "${var.project}-media-cleanup-${var.environment}"
  schedule_expression          = var.media_cleanup_schedule_expression
  schedule_expression_timezone = "UTC"
  state                        = var.bootstrap_mode ? "DISABLED" : "ENABLED"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_ecs_cluster.main.arn
    role_arn = var.scheduler_execution_role_arn

    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.worker.arn
      task_count          = 1

      # EventBridge Scheduler's ECS target's launch_type only accepts
      # EC2/FARGATE/EXTERNAL -- the same enum ecs:RunTask itself accepts.
      # FARGATE_SPOT is never a valid launch_type value anywhere in the ECS
      # API; it is only ever selected through a capacity provider strategy,
      # exactly like on the aws_ecs_service resources above.
      # launch_type and capacity_provider_strategy are mutually exclusive.
      launch_type = var.use_fargate_spot ? null : "FARGATE"

      dynamic "capacity_provider_strategy" {
        for_each = var.use_fargate_spot ? [1] : []
        content {
          capacity_provider = "FARGATE_SPOT"
          weight            = 100
        }
      }

      network_configuration {
        subnets          = var.private_app_subnet_ids
        security_groups  = [var.ecs_tasks_security_group_id]
        assign_public_ip = false
      }
    }

    retry_policy {
      maximum_retry_attempts = 2
    }
  }

  # `deploy-worker` in .github/workflows/deploy.yml updates
  # target.ecs_parameters.task_definition_arn directly (via
  # `aws scheduler update-schedule`, waited on and failing the deploy job
  # if it cannot be applied) to the exact new worker revision after every
  # deploy, out-of-band from Terraform -- otherwise the schedule would keep
  # running whatever image was current at the last `terraform apply`, not
  # the image just deployed.
  #
  # This is deliberately NOT hidden via `lifecycle.ignore_changes`: a later
  # infra-only `terraform apply` (var.backend_image defaults to the
  # "latest" tag, which the deploy workflow also always pushes alongside
  # the immutable SHA tag) will reset this back to the latest registered
  # revision, a self-healing, still-correct state, not a stale or broken
  # one -- and leaving it visible in `terraform plan` output keeps that
  # reset an explicit, reviewable change instead of silently-ignored drift.
}
