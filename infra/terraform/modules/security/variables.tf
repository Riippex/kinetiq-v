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
  description = "The ID of the VPC"
  type        = string
}

variable "vision_security_group_id" {
  description = "Security group attached to the private Vision ECS tasks"
  type        = string
}
