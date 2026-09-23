variable "aws_region" {
  description = "AWS region for infrastructure deployment"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name (hackathon, staging, prod)"
  type        = string
  default     = "hackathon"
}

variable "project" {
  description = "Project name tag"
  type        = string
  default     = "kinetiq-v"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "Availability zones to deploy subnets into"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}

variable "single_nat_gateway" {
  description = "Whether to use a single NAT Gateway for cost optimization in hackathon (~$32/mo savings)"
  type        = bool
  default     = true
}

variable "use_fargate_spot" {
  description = "Whether to use FARGATE_SPOT for compute cost savings (~70% off standard Fargate)"
  type        = bool
  default     = true
}

variable "budget_limit_amount" {
  description = "Monthly budget limit in USD"
  type        = string
  default     = "50.0"
}

variable "budget_notification_emails" {
  description = "List of email addresses to receive AWS budget threshold alerts"
  type        = list(string)
  default     = []
}

variable "github_repository" {
  description = "GitHub repository for OIDC trust (e.g. Riippex/kinetiq-v)"
  type        = string
  default     = "Riippex/kinetiq-v"
}

variable "create_oidc_provider" {
  description = "Whether to create the GitHub Actions OIDC provider (set false if already present in account)"
  type        = bool
  default     = true
}

variable "existing_oidc_provider_arn" {
  description = "ARN of existing GitHub Actions OIDC provider if create_oidc_provider is false"
  type        = string
  default     = ""
}

variable "certificate_arn" {
  description = "Optional ACM certificate ARN for ALB HTTPS listener"
  type        = string
  default     = ""
}

variable "backend_image_tag" {
  description = "Tag of backend container image in ECR (defaults to latest)"
  type        = string
  default     = "latest"
}

variable "web_image_tag" {
  description = "Tag of web container image in ECR (defaults to latest)"
  type        = string
  default     = "latest"
}
