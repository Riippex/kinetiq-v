output "alb_dns_name" {
  description = "Public DNS name of the Application Load Balancer"
  value       = module.compute.alb_dns_name
}

output "application_url" {
  description = "Canonical application entry URL -- https only once a real HTTPS listener (certificate_arn or domain_name) is configured, http otherwise"
  value       = module.compute.public_origin
}

output "graphql_endpoint" {
  description = "Direct GraphQL API endpoint on the canonical origin"
  value       = "${module.compute.public_origin}/graphql/"
}

output "mcp_endpoint" {
  description = "Alexa+ MCP Streamable HTTP endpoint on the canonical origin"
  value       = "${module.compute.public_origin}/mcp"
}

output "has_https" {
  description = "Whether the ALB currently has a real HTTPS listener"
  value       = module.compute.has_https
}

output "cognito_hosted_ui_domain" {
  description = "Cognito Hosted UI domain serving the OAuth authorization-code flow"
  value       = module.identity.hosted_ui_domain
}

output "media_cleanup_schedule_name" {
  description = "EventBridge Scheduler schedule that runs the media-cleanup task"
  value       = module.compute.media_cleanup_schedule_name
}

output "cognito_user_pool_id" {
  description = "Cognito User Pool ID"
  value       = module.identity.user_pool_id
}

output "cognito_issuer_url" {
  description = "Cognito OIDC Issuer URL for token verification"
  value       = module.identity.issuer_url
}

output "cognito_jwks_url" {
  description = "Cognito JWKS URL for MCP RS256 token verification"
  value       = module.identity.jwks_url
}

output "cognito_web_client_id" {
  description = "Cognito Web App Client ID"
  value       = module.identity.web_client_id
}

output "cognito_mobile_client_id" {
  description = "Cognito Mobile App Client ID"
  value       = module.identity.mobile_client_id
}

output "media_bucket_name" {
  description = "Private S3 media bucket name"
  value       = module.storage.bucket_id
}

output "backend_ecr_repository_url" {
  description = "ECR repository URL for backend container images"
  value       = module.ecr.backend_repository_url
}

output "web_ecr_repository_url" {
  description = "ECR repository URL for web container images"
  value       = module.ecr.web_repository_url
}

output "github_deployer_role_arn" {
  description = "IAM Role ARN for GitHub Actions OIDC deployment"
  value       = module.iam.github_deployer_role_arn
}

output "event_bus_name" {
  description = "Custom EventBridge bus name for domain events"
  value       = module.messaging.event_bus_name
}

output "database_secret_arn" {
  description = "Secrets Manager ARN for database credentials"
  value       = module.database.secret_arn
}

output "redis_secret_arn" {
  description = "Secrets Manager ARN for Redis credentials"
  value       = module.cache.secret_arn
}
