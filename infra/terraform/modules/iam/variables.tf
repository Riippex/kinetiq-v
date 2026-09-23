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

variable "github_repository" {
  description = "GitHub repository for OIDC trust, as <owner>/<repo> (e.g. Riippex/kinetiq-v)"
  type        = string
  default     = "Riippex/kinetiq-v"

  validation {
    condition     = can(regex("^[^/]+/[^/]+$", var.github_repository))
    error_message = "github_repository must be exactly <owner>/<repo>, e.g. Riippex/kinetiq-v."
  }
}

variable "github_oidc_environment" {
  description = "GitHub Environment name the deploy workflow must run under for the OIDC role to be assumable"
  type        = string
  default     = "hackathon"
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

# Required: builds the environment-scoped immutable OIDC subject this role
# trusts (see aws_iam_role.github_deployer's assume_role_policy in main.tf).
# Terraform can only verify this looks like a numeric ID, not that it is
# actually this repository's -- retrieve the real value with:
#   gh api repos/<owner>/<repo> --jq .id
variable "github_repository_id" {
  description = "Numeric GitHub repository ID, used to build the immutable OIDC subject claim this role trusts."
  type        = string

  validation {
    condition     = can(regex("^[0-9]+$", var.github_repository_id))
    error_message = "github_repository_id must be a non-empty numeric string -- the repository's numeric ID, e.g. from `gh api repos/<owner>/<repo> --jq .id`."
  }
}

# Required: see github_repository_id above. Retrieve the real value with:
#   gh api users/<owner> --jq .id   (user-owned repository)
#   gh api orgs/<owner> --jq .id    (organization-owned repository)
variable "github_repository_owner_id" {
  description = "Numeric GitHub repository owner (user or org) ID, used to build the immutable OIDC subject claim this role trusts."
  type        = string

  validation {
    condition     = can(regex("^[0-9]+$", var.github_repository_owner_id))
    error_message = "github_repository_owner_id must be a non-empty numeric string -- the owner's numeric ID, e.g. from `gh api users/<owner> --jq .id` or `gh api orgs/<owner> --jq .id`."
  }
}
