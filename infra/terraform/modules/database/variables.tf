variable "environment" {
  description = "Deployment environment name"
  type        = string
}

variable "project" {
  description = "Project name tag"
  type        = string
  default     = "kinetiq-v"
}

variable "subnet_ids" {
  description = "Subnet IDs for the DB subnet group (private data subnets)"
  type        = list(string)
}

variable "security_group_id" {
  description = "Security group ID for RDS"
  type        = string
}

variable "db_name" {
  description = "Name of the initial database"
  type        = string
  default     = "kinetiq"
}

variable "db_username" {
  description = "Master username for RDS PostgreSQL"
  type        = string
  default     = "kinetiq_app"
}

variable "instance_class" {
  description = "RDS instance class (Arm64 db.t4g.micro is cost-optimized for hackathon at ~$15/mo)"
  type        = string
  default     = "db.t4g.micro"
}

variable "allocated_storage" {
  description = "Allocated storage in GB"
  type        = number
  default     = 20
}

variable "max_allocated_storage" {
  description = "Maximum storage limit in GB for autoscaling"
  type        = number
  default     = 50
}

variable "engine_version" {
  description = "PostgreSQL engine version"
  type        = string
  default     = "17.11"
}

variable "multi_az" {
  description = "Whether to enable Multi-AZ deployment (set false for hackathon to save ~$15/mo)"
  type        = bool
  default     = false
}

variable "backup_retention_period" {
  description = "Number of days to retain automated backups"
  type        = number
  default     = 7
}

variable "deletion_protection" {
  description = "Whether to prevent accidental deletion"
  type        = bool
  default     = false
}

variable "skip_final_snapshot" {
  description = "Whether to skip final snapshot when destroying (set true for hackathon teardown)"
  type        = bool
  default     = true
}
