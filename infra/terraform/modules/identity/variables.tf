variable "environment" {
  description = "Deployment environment name"
  type        = string
}

variable "project" {
  description = "Project name tag"
  type        = string
  default     = "kinetiq-v"
}

variable "web_callback_urls" {
  description = "Callback URLs for Cognito Web App Client"
  type        = list(string)
  default     = ["http://localhost:3000/api/auth/callback/cognito"]
}

variable "web_logout_urls" {
  description = "Logout URLs for Cognito Web App Client"
  type        = list(string)
  default     = ["http://localhost:3000"]
}

variable "cognito_domain_prefix" {
  description = "Domain prefix for the Cognito Hosted UI (<prefix>.auth.<region>.amazoncognito.com); the OAuth authorization/token endpoints have no other usable domain without this"
  type        = string
}

variable "mobile_callback_urls" {
  description = "Callback URLs for Cognito Mobile App Client"
  type        = list(string)
  default     = ["kinetiq://callback", "exp://127.0.0.1:8081/--/callback"]
}

variable "mobile_logout_urls" {
  description = "Logout URLs for Cognito Mobile App Client"
  type        = list(string)
  default     = ["kinetiq://logout"]
}
