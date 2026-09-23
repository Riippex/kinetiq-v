output "primary_endpoint_address" {
  description = "Primary endpoint address for the Redis replication group"
  value       = aws_elasticache_replication_group.main.primary_endpoint_address
}

output "port" {
  description = "Port the Redis service listens on"
  value       = aws_elasticache_replication_group.main.port
}

output "secret_arn" {
  description = "ARN of the Secrets Manager secret containing Redis credentials"
  value       = aws_secretsmanager_secret.redis_credentials.arn
}
