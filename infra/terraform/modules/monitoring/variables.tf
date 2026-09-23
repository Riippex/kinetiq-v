variable "environment" {
  description = "Deployment environment name"
  type        = string
}

variable "project" {
  description = "Project name tag"
  type        = string
  default     = "kinetiq-v"
}

variable "log_retention_in_days" {
  description = "Specifies the number of days you want to retain log events in CloudWatch"
  type        = number
  default     = 14
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
