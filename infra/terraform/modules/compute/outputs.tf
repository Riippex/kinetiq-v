output "alb_dns_name" {
  description = "DNS name of the Application Load Balancer"
  value       = aws_lb.main.dns_name
}

output "alb_arn" {
  description = "ARN of the Application Load Balancer"
  value       = aws_lb.main.arn
}

output "ecs_cluster_id" {
  description = "ID of the ECS cluster"
  value       = aws_ecs_cluster.main.id
}

output "ecs_cluster_name" {
  description = "Name of the ECS cluster"
  value       = aws_ecs_cluster.main.name
}

output "ecs_cluster_arn" {
  description = "ARN of the ECS cluster"
  value       = aws_ecs_cluster.main.arn
}

output "backend_service_name" {
  description = "Name of the backend ECS service"
  value       = aws_ecs_service.backend.name
}

output "web_service_name" {
  description = "Name of the web ECS service"
  value       = aws_ecs_service.web.name
}

output "worker_service_name" {
  description = "Name of the worker ECS service"
  value       = aws_ecs_service.worker.name
}

output "migrate_task_definition_arn" {
  description = "ARN of the migration task definition"
  value       = aws_ecs_task_definition.migrate.arn
}
