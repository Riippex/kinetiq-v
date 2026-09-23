# Application Load Balancer Security Group
resource "aws_security_group" "alb" {
  name        = "${var.project}-${var.environment}-alb-sg"
  description = "Security group for internet-facing Application Load Balancer"
  vpc_id      = var.vpc_id

  tags = {
    Name        = "${var.project}-${var.environment}-alb-sg"
    Environment = var.environment
    Project     = var.project
  }
}

resource "aws_security_group_rule" "alb_http_in" {
  type              = "ingress"
  security_group_id = aws_security_group.alb.id
  from_port         = 80
  to_port           = 80
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  description       = "Allow inbound HTTP from internet"
}

resource "aws_security_group_rule" "alb_https_in" {
  type              = "ingress"
  security_group_id = aws_security_group.alb.id
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  description       = "Allow inbound HTTPS from internet"
}

resource "aws_security_group_rule" "alb_backend_out" {
  type                     = "egress"
  security_group_id        = aws_security_group.alb.id
  from_port                = 8000
  to_port                  = 8000
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.ecs_tasks.id
  description              = "Forward traffic to backend ECS tasks on port 8000"
}

resource "aws_security_group_rule" "alb_web_out" {
  type                     = "egress"
  security_group_id        = aws_security_group.alb.id
  from_port                = 3000
  to_port                  = 3000
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.ecs_tasks.id
  description              = "Forward traffic to web ECS tasks on port 3000"
}

# ECS Fargate Tasks Security Group
resource "aws_security_group" "ecs_tasks" {
  name        = "${var.project}-${var.environment}-ecs-tasks-sg"
  description = "Security group for ECS Fargate tasks (backend, web, worker)"
  vpc_id      = var.vpc_id

  tags = {
    Name        = "${var.project}-${var.environment}-ecs-tasks-sg"
    Environment = var.environment
    Project     = var.project
  }
}

resource "aws_security_group_rule" "ecs_backend_in" {
  type                     = "ingress"
  security_group_id        = aws_security_group.ecs_tasks.id
  from_port                = 8000
  to_port                  = 8000
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.alb.id
  description              = "Allow inbound from ALB on port 8000"
}

resource "aws_security_group_rule" "ecs_web_in" {
  type                     = "ingress"
  security_group_id        = aws_security_group.ecs_tasks.id
  from_port                = 3000
  to_port                  = 3000
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.alb.id
  description              = "Allow inbound from ALB on port 3000"
}

resource "aws_security_group_rule" "ecs_https_out" {
  type              = "egress"
  security_group_id = aws_security_group.ecs_tasks.id
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  description       = "Allow outbound HTTPS for AWS APIs (ECR, CloudWatch, Secrets Manager, S3, Bedrock, Cognito)"
}

resource "aws_security_group_rule" "ecs_rds_out" {
  type                     = "egress"
  security_group_id        = aws_security_group.ecs_tasks.id
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.rds.id
  description              = "Allow outbound to RDS PostgreSQL on port 5432"
}

resource "aws_security_group_rule" "ecs_elasticache_out" {
  type                     = "egress"
  security_group_id        = aws_security_group.ecs_tasks.id
  from_port                = 6379
  to_port                  = 6379
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.elasticache.id
  description              = "Allow outbound to ElastiCache Redis on port 6379"
}

# RDS PostgreSQL Security Group
resource "aws_security_group" "rds" {
  name        = "${var.project}-${var.environment}-rds-sg"
  description = "Security group for private RDS PostgreSQL instance"
  vpc_id      = var.vpc_id

  tags = {
    Name        = "${var.project}-${var.environment}-rds-sg"
    Environment = var.environment
    Project     = var.project
  }
}

resource "aws_security_group_rule" "rds_postgres_in" {
  type                     = "ingress"
  security_group_id        = aws_security_group.rds.id
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.ecs_tasks.id
  description              = "Allow inbound PostgreSQL connections strictly from ECS tasks"
}

# ElastiCache Redis Security Group
resource "aws_security_group" "elasticache" {
  name        = "${var.project}-${var.environment}-elasticache-sg"
  description = "Security group for private ElastiCache Redis instance"
  vpc_id      = var.vpc_id

  tags = {
    Name        = "${var.project}-${var.environment}-elasticache-sg"
    Environment = var.environment
    Project     = var.project
  }
}

resource "aws_security_group_rule" "elasticache_redis_in" {
  type                     = "ingress"
  security_group_id        = aws_security_group.elasticache.id
  from_port                = 6379
  to_port                  = 6379
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.ecs_tasks.id
  description              = "Allow inbound Redis connections strictly from ECS tasks"
}
