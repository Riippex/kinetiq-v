output "event_bus_name" {
  description = "Name of the custom EventBridge bus"
  value       = aws_cloudwatch_event_bus.main.name
}

output "event_bus_arn" {
  description = "ARN of the custom EventBridge bus"
  value       = aws_cloudwatch_event_bus.main.arn
}

output "workout_events_queue_url" {
  description = "URL of the workout events consumer SQS queue"
  value       = aws_sqs_queue.workout_events.id
}

output "workout_events_queue_arn" {
  description = "ARN of the workout events consumer SQS queue"
  value       = aws_sqs_queue.workout_events.arn
}

output "workout_events_dlq_url" {
  description = "URL of the workout events consumer DLQ"
  value       = aws_sqs_queue.workout_events_dlq.id
}

output "workout_events_dlq_arn" {
  description = "ARN of the workout events consumer DLQ"
  value       = aws_sqs_queue.workout_events_dlq.arn
}
