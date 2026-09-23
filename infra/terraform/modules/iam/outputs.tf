output "ecs_execution_role_arn" {
  description = "ARN of the ECS task execution role"
  value       = aws_iam_role.ecs_execution_role.arn
}

output "ecs_execution_role_name" {
  description = "Name of the ECS task execution role"
  value       = aws_iam_role.ecs_execution_role.name
}

output "backend_task_role_arn" {
  description = "ARN of the backend task role"
  value       = aws_iam_role.backend_task_role.arn
}

output "worker_task_role_arn" {
  description = "ARN of the worker task role"
  value       = aws_iam_role.worker_task_role.arn
}

output "github_deployer_role_arn" {
  description = "ARN of the GitHub Actions OIDC deployer role"
  value       = aws_iam_role.github_deployer.arn
}
