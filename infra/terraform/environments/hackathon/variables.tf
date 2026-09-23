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
  description = "GitHub repository for OIDC trust, as <owner>/<repo> (e.g. Riippex/kinetiq-v)"
  type        = string
  default     = "Riippex/kinetiq-v"

  validation {
    condition     = can(regex("^[^/]+/[^/]+$", var.github_repository))
    error_message = "github_repository must be exactly <owner>/<repo>, e.g. Riippex/kinetiq-v."
  }
}

# Required: builds the environment-scoped immutable OIDC subject
# (repo:<owner>@<owner-id>/<repo>@<repo-id>:environment:<environment>) that
# the GitHub Actions deployer role trusts -- see
# infra/terraform/modules/iam/main.tf and "GitHub OIDC immutable subject"
# in docs/runbooks/infrastructure-bootstrap.md for how to retrieve and
# independently confirm the real values. Terraform only verifies these
# look like numeric IDs, not that they are genuinely this repository's.
variable "github_repository_id" {
  description = "Numeric GitHub repository ID. Retrieve with: gh api repos/<owner>/<repo> --jq .id"
  type        = string

  validation {
    condition     = can(regex("^[0-9]+$", var.github_repository_id))
    error_message = "github_repository_id must be a non-empty numeric string -- the repository's numeric ID, e.g. from `gh api repos/<owner>/<repo> --jq .id`."
  }
}

variable "github_repository_owner_id" {
  description = "Numeric GitHub repository owner (user or org) ID. Retrieve with: gh api users/<owner> --jq .id (user) or gh api orgs/<owner> --jq .id (org)"
  type        = string

  validation {
    condition     = can(regex("^[0-9]+$", var.github_repository_owner_id))
    error_message = "github_repository_owner_id must be a non-empty numeric string -- the owner's numeric ID, e.g. from `gh api users/<owner> --jq .id` or `gh api orgs/<owner> --jq .id`."
  }
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
  description = "Optional, pre-issued ACM certificate ARN for the ALB HTTPS listener, in place of Terraform's own domain_name-driven certificate issuance. MUST be a certificate actually issued for exactly domain_name."
  type        = string
  default     = ""

  validation {
    condition     = var.certificate_arn == "" || var.domain_name != ""
    error_message = "certificate_arn is set without domain_name: set domain_name to the exact public hostname that the certificate at certificate_arn was issued for."
  }
}

variable "domain_name" {
  description = "Canonical public domain for this environment. Required: the hackathon deployment must have one real, usable HTTPS public origin before it is considered deployable -- there is no HTTP-only mode. Must already have a public Route53 hosted zone in this account -- see docs/runbooks/infrastructure-bootstrap.md and infra/terraform/modules/compute/variables.tf for the full explanation."
  type        = string

  validation {
    condition     = var.domain_name != ""
    error_message = "domain_name is required: the hackathon environment must have one real, usable HTTPS public origin. Register a domain, create a public Route53 hosted zone for it, and set domain_name (see docs/runbooks/infrastructure-bootstrap.md)."
  }
}

variable "github_oidc_environment" {
  description = "GitHub Environment name the deploy workflow must run under for the OIDC deployer role to be assumable"
  type        = string
  default     = "hackathon"
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
