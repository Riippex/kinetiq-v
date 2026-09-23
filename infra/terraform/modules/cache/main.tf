resource "random_password" "redis_auth_token" {
  length  = 32
  special = false
}

# Subnet Group
resource "aws_elasticache_subnet_group" "main" {
  name        = "${var.project}-${var.environment}-redis-subnet-group"
  subnet_ids  = var.subnet_ids
  description = "Subnet group for private ElastiCache Redis clusters"

  tags = {
    Name        = "${var.project}-${var.environment}-redis-subnet-group"
    Environment = var.environment
    Project     = var.project
  }
}

# Parameter Group
resource "aws_elasticache_parameter_group" "main" {
  name        = "${var.project}-${var.environment}-redis7-params"
  family      = "redis7"
  description = "Custom parameter group for Redis 7"

  tags = {
    Name        = "${var.project}-${var.environment}-redis7-params"
    Environment = var.environment
    Project     = var.project
  }
}

# ElastiCache Redis Replication Group
resource "aws_elasticache_replication_group" "main" {
  replication_group_id       = "${var.project}-${var.environment}-redis"
  description                = "Redis cluster for Kinetiq cache, channel layer, and display pairing"
  node_type                  = var.node_type
  num_cache_clusters         = var.num_cache_clusters
  port                       = 6379
  parameter_group_name       = aws_elasticache_parameter_group.main.name
  subnet_group_name          = aws_elasticache_subnet_group.main.name
  security_group_ids         = [var.security_group_id]
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  auth_token                 = random_password.redis_auth_token.result
  automatic_failover_enabled = var.num_cache_clusters > 1
  auto_minor_version_upgrade = true
  apply_immediately          = true

  tags = {
    Name        = "${var.project}-${var.environment}-redis"
    Environment = var.environment
    Project     = var.project
  }
}

# Secrets Manager Secret storing Redis Credentials and REDIS_URL
resource "aws_secretsmanager_secret" "redis_credentials" {
  name                    = "${var.project}/${var.environment}/redis"
  description             = "Connection details and REDIS_URL for ElastiCache Redis"
  recovery_window_in_days = 0

  tags = {
    Environment = var.environment
    Project     = var.project
  }
}

resource "aws_secretsmanager_secret_version" "redis_credentials" {
  secret_id = aws_secretsmanager_secret.redis_credentials.id
  secret_string = jsonencode({
    host       = aws_elasticache_replication_group.main.primary_endpoint_address
    port       = 6379
    auth_token = random_password.redis_auth_token.result
    redis_url  = "rediss://:${random_password.redis_auth_token.result}@${aws_elasticache_replication_group.main.primary_endpoint_address}:6379/0"
  })
}
