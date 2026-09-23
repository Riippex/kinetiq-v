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
  description = "Optional, pre-issued ACM certificate ARN for the HTTPS listener, in place of Terraform's own domain_name-driven certificate issuance. MUST be a certificate actually issued for exactly domain_name -- see its validation below."
  type        = string
  default     = ""

  validation {
    # A certificate has no meaning without the exact public hostname it was
    # issued for: presenting *some* certificate for a hostname it does not
    # cover is a TLS validation failure for every real client, and
    # advertising the ALB's own AWS-generated DNS name under someone else's
    # certificate would be actively misleading.
    condition     = var.certificate_arn == "" || var.domain_name != ""
    error_message = "certificate_arn is set without domain_name: set domain_name to the exact public hostname that the certificate at certificate_arn was issued for."
  }
}

variable "domain_name" {
  description = <<-EOT
    Canonical public domain for this environment (e.g. hackathon.kinetiq.example).
    Required: the hackathon deployment must have one real, usable HTTPS public origin
    before it is considered deployable -- there is no HTTP-only mode. Must already have a
    public Route53 hosted zone in this account. Terraform requests and DNS-validates an ACM
    certificate for it (unless certificate_arn is supplied instead), aliases it to the ALB,
    and every origin-derived value (Cognito callbacks/logout, S3 CORS, Django allowed hosts,
    GraphQL/MCP URLs) is derived from it over HTTPS. Local-development-only defaults
    (localhost) live solely in each module's own variables (identity, storage) for direct,
    non-hackathon-root use of those modules -- never here.
  EOT
  type        = string

  validation {
    condition     = var.domain_name != ""
    error_message = "domain_name is required: the hackathon environment must have one real, usable HTTPS public origin. Register a domain, create a public Route53 hosted zone for it, and set domain_name (see docs/runbooks/infrastructure-bootstrap.md)."
  }
}

variable "use_fargate_spot" {
  description = "Whether to use FARGATE_SPOT for cost savings (~70% off compute)"
  type        = bool
  default     = true
}

variable "scheduler_execution_role_arn" {
  description = "ARN of the EventBridge Scheduler execution role for the media-cleanup task"
  type        = string
}

variable "media_cleanup_schedule_expression" {
  description = "EventBridge Scheduler rate/cron expression for the media-cleanup task"
  type        = string
  default     = "rate(15 minutes)"
}
