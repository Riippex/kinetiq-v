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
  description = "Subnet IDs for ElastiCache subnet group (private data subnets)"
  type        = list(string)
}

variable "security_group_id" {
  description = "Security group ID for ElastiCache Redis"
  type        = string
}

variable "node_type" {
  description = "ElastiCache node type (Arm64 cache.t4g.micro is cost-optimized for hackathon at ~$12/mo)"
  type        = string
  default     = "cache.t4g.micro"
}

variable "num_cache_clusters" {
  description = "Number of cache clusters (1 for single-node hackathon development)"
  type        = number
  default     = 1
}
