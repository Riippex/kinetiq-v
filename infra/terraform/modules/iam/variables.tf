variable "environment" {
  description = "Deployment environment name"
  type        = string
}

variable "project" {
  description = "Project name tag"
  type        = string
  default     = "kinetiq-v"
}

variable "media_bucket_arn" {
  description = "ARN of the private S3 media bucket"
  type        = string
}

variable "secret_arns" {
  description = "List of Secrets Manager ARNs the ECS task execution role may read"
  type        = list(string)
}

variable "event_bus_arn" {
  description = "ARN of the custom EventBridge bus"
  type        = string
}

variable "sqs_queue_arn" {
  description = "ARN of the consumer SQS queue for the worker"
  type        = string
}

variable "backend_repository_arn" {
  description = "ARN of the backend ECR repository"
  type        = string
}

variable "web_repository_arn" {
  description = "ARN of the web ECR repository"
  type        = string
}

variable "ecs_cluster_arn" {
  description = "ARN of the ECS cluster"
  type        = string
}

variable "github_repository" {
  description = "GitHub repository for OIDC trust (e.g. Riippex/kinetiq-v)"
  type        = string
  default     = "Riippex/kinetiq-v"
}

variable "create_oidc_provider" {
  description = "Whether to create the GitHub Actions OIDC provider (set false if already present in the account)"
  type        = bool
  default     = true
}

variable "existing_oidc_provider_arn" {
  description = "ARN of existing GitHub Actions OIDC provider if create_oidc_provider is false"
  type        = string
  default     = ""
}
