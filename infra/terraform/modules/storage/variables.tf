variable "environment" {
  description = "Deployment environment name"
  type        = string
}

variable "project" {
  description = "Project name tag"
  type        = string
  default     = "kinetiq-v"
}

variable "account_id" {
  description = "AWS Account ID for globally unique S3 bucket naming"
  type        = string
}

variable "cors_allowed_origins" {
  description = "Allowed origins for CORS on the private media bucket"
  type        = list(string)
  default     = ["http://localhost:3000", "http://localhost:8000"]
}
