output "backend_log_group_name" {
  description = "Name of the backend CloudWatch log group"
  value       = aws_cloudwatch_log_group.backend.name
}

output "web_log_group_name" {
  description = "Name of the web CloudWatch log group"
  value       = aws_cloudwatch_log_group.web.name
}

output "worker_log_group_name" {
  description = "Name of the worker CloudWatch log group"
  value       = aws_cloudwatch_log_group.worker.name
}

output "migrate_log_group_name" {
  description = "Name of the migrate CloudWatch log group"
  value       = aws_cloudwatch_log_group.migrate.name
}

output "budget_name" {
  description = "Name of the AWS budget"
  value       = aws_budgets_budget.monthly.name
}
