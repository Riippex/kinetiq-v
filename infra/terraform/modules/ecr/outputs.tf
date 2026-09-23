output "backend_repository_url" {
  description = "URL of the backend ECR repository"
  value       = aws_ecr_repository.backend.repository_url
}

output "backend_repository_arn" {
  description = "ARN of the backend ECR repository"
  value       = aws_ecr_repository.backend.arn
}

output "web_repository_url" {
  description = "URL of the web ECR repository"
  value       = aws_ecr_repository.web.repository_url
}

output "web_repository_arn" {
  description = "ARN of the web ECR repository"
  value       = aws_ecr_repository.web.arn
}
