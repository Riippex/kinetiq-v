variable "environment" {
  description = "Deployment environment name"
  type        = string
}

variable "project" {
  description = "Project name tag"
  type        = string
  default     = "kinetiq-v"
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "public_subnet_ids" {
  description = "Subnet IDs for the public Application Load Balancer"
  type        = list(string)
}

variable "private_app_subnet_ids" {
  description = "Subnet IDs for ECS Fargate tasks"
  type        = list(string)
}

variable "alb_security_group_id" {
  description = "Security group ID for the ALB"
  type        = string
}

variable "ecs_tasks_security_group_id" {
  description = "Security group ID for ECS tasks"
  type        = string
}

variable "ecs_execution_role_arn" {
  description = "ARN of the ECS task execution role"
  type        = string
}

variable "backend_task_role_arn" {
  description = "ARN of the backend task role"
  type        = string
}

variable "worker_task_role_arn" {
  description = "ARN of the worker task role"
  type        = string
}

variable "backend_image" {
  description = "ECR image URI for the backend container (e.g. repo:tag)"
  type        = string
}

variable "web_image" {
  description = "ECR image URI for the web container (e.g. repo:tag)"
  type        = string
}

variable "media_bucket_id" {
  description = "Name of the S3 media bucket"
  type        = string
}

variable "database_secret_arn" {
  description = "ARN of the database secret in Secrets Manager"
  type        = string
}

variable "redis_secret_arn" {
  description = "ARN of the Redis secret in Secrets Manager"
  type        = string
}

variable "django_secret_key_arn" {
  description = "ARN of the Django secret key in Secrets Manager"
  type        = string
}

variable "cognito_issuer_url" {
  description = "Cognito OIDC issuer URL"
  type        = string
}

variable "cognito_jwks_url" {
  description = "Cognito OIDC JWKS URL"
  type        = string
}

variable "cognito_web_client_id" {
  description = "Cognito Web Client ID"
  type        = string
}

variable "certificate_arn" {
  description = "Optional ACM certificate ARN for HTTPS listener"
  type        = string
  default     = ""
}

variable "use_fargate_spot" {
  description = "Whether to use FARGATE_SPOT for cost savings (~70% off compute)"
  type        = bool
  default     = true
}
