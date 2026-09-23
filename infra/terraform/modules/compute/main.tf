data "aws_region" "current" {}

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

# HTTP Listener on port 80 (default routes to Web)
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}

# Routing rule: forward /api/*, /graphql*, /ws/*, /mcp* to Backend
resource "aws_lb_listener_rule" "backend_routes" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.backend.arn
  }

  condition {
    path_pattern {
      values = ["/api/*", "/graphql*", "/ws/*", "/mcp*"]
    }
  }
}

# Optional HTTPS Listener if ACM certificate ARN is provided
resource "aws_lb_listener" "https" {
  count             = var.certificate_arn != "" ? 1 : 0
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}

resource "aws_lb_listener_rule" "backend_routes_https" {
  count        = var.certificate_arn != "" ? 1 : 0
  listener_arn = aws_lb_listener.https[0].arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.backend.arn
  }

  condition {
    path_pattern {
      values = ["/api/*", "/graphql*", "/ws/*", "/mcp*"]
    }
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
        { name = "DJANGO_ALLOWED_HOSTS", value = "*" },
        { name = "AWS_REGION", value = data.aws_region.current.name },
        { name = "MEDIA_S3_BUCKET", value = var.media_bucket_id },
        { name = "DISPLAY_PAIRING_STORE", value = "redis" },
        { name = "MCP_OIDC_ISSUER", value = var.cognito_issuer_url },
        { name = "MCP_OIDC_AUDIENCE", value = var.cognito_web_client_id },
        { name = "MCP_OIDC_JWKS_URL", value = var.cognito_jwks_url },
        { name = "MCP_OIDC_REQUIRED_SCOPE", value = "kinetiq/coach" },
        { name = "MCP_OIDC_TOKEN_USE", value = "access" },
        { name = "MCP_RESOURCE_URL", value = "https://${aws_lb.main.dns_name}/mcp" }
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
        { name = "NEXT_PUBLIC_GRAPHQL_ENDPOINT", value = "https://${aws_lb.main.dns_name}/graphql" }
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
  desired_count   = 1

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
  desired_count   = 1

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

  depends_on = [aws_lb_listener.http]

  tags = {
    Name        = "${var.project}-web-service"
    Environment = var.environment
    Project     = var.project
  }
}

resource "aws_ecs_service" "worker" {
  name            = "${var.project}-worker-${var.environment}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = 1

  capacity_provider_strategy {
    capacity_provider = var.use_fargate_spot ? "FARGATE_SPOT" : "FARGATE"
    weight            = 100
  }

  network_configuration {
    subnets          = var.private_app_subnet_ids
    security_groups  = [var.ecs_tasks_security_group_id]
    assign_public_ip = false
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  tags = {
    Name        = "${var.project}-worker-service"
    Environment = var.environment
    Project     = var.project
  }
}
