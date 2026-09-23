# Custom EventBridge Bus for Domain Events
resource "aws_cloudwatch_event_bus" "main" {
  name = "${var.project}-events-${var.environment}"

  tags = {
    Name        = "${var.project}-events-${var.environment}"
    Environment = var.environment
    Project     = var.project
  }
}

# EventBridge Delivery DLQ (captures delivery failures before reaching SQS)
resource "aws_sqs_queue" "eventbridge_dlq" {
  name                      = "${var.project}-eventbridge-dlq-${var.environment}"
  message_retention_seconds = 1209600 # 14 days
  sqs_managed_sse_enabled   = true

  tags = {
    Name        = "${var.project}-eventbridge-dlq-${var.environment}"
    Environment = var.environment
    Project     = var.project
  }
}

# Consumer DLQ (captures messages exceeding retry budget during consumer processing)
resource "aws_sqs_queue" "workout_events_dlq" {
  name                      = "${var.project}-workout-events-dlq-${var.environment}"
  message_retention_seconds = 1209600 # 14 days
  sqs_managed_sse_enabled   = true

  tags = {
    Name        = "${var.project}-workout-events-dlq-${var.environment}"
    Environment = var.environment
    Project     = var.project
  }
}

# Consumer Main Queue for Kinetiq Workers
resource "aws_sqs_queue" "workout_events" {
  name                       = "${var.project}-workout-events-${var.environment}"
  visibility_timeout_seconds = 60
  message_retention_seconds  = 345600 # 4 days
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.workout_events_dlq.arn
    maxReceiveCount     = 5
  })

  tags = {
    Name        = "${var.project}-workout-events-${var.environment}"
    Environment = var.environment
    Project     = var.project
  }
}

# Policy allowing EventBridge to send messages to the consumer queue
resource "aws_sqs_queue_policy" "workout_events_subscription" {
  queue_url = aws_sqs_queue.workout_events.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowEventBridgeToSendMessages"
        Effect = "Allow"
        Principal = {
          Service = "events.amazonaws.com"
        }
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.workout_events.arn
        Condition = {
          ArnEquals = {
            "aws:SourceArn" = aws_cloudwatch_event_rule.workout_events.arn
          }
        }
      }
    ]
  })
}

# Policy allowing EventBridge to send delivery failures to the eventbridge DLQ
resource "aws_sqs_queue_policy" "eventbridge_dlq_subscription" {
  queue_url = aws_sqs_queue.eventbridge_dlq.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowEventBridgeToSendFailures"
        Effect = "Allow"
        Principal = {
          Service = "events.amazonaws.com"
        }
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.eventbridge_dlq.arn
      }
    ]
  })
}

# EventBridge Rule routing domain events to the worker queue
resource "aws_cloudwatch_event_rule" "workout_events" {
  name           = "${var.project}-workout-events-rule-${var.environment}"
  description    = "Route Kinetiq domain events to the worker consumer queue"
  event_bus_name = aws_cloudwatch_event_bus.main.name

  event_pattern = jsonencode({
    source = [
      "kinetiq.workouts",
      "kinetiq.goals",
      "kinetiq.routines",
      "kinetiq.progress",
      "kinetiq.media"
    ]
  })

  tags = {
    Name        = "${var.project}-workout-events-rule-${var.environment}"
    Environment = var.environment
    Project     = var.project
  }
}

# EventBridge Target
resource "aws_cloudwatch_event_target" "workout_events" {
  rule           = aws_cloudwatch_event_rule.workout_events.name
  event_bus_name = aws_cloudwatch_event_bus.main.name
  target_id      = "SendToWorkoutEventsQueue"
  arn            = aws_sqs_queue.workout_events.arn

  dead_letter_config {
    arn = aws_sqs_queue.eventbridge_dlq.arn
  }

  retry_policy {
    maximum_event_age_in_seconds = 86400
    maximum_retry_attempts       = 10
  }
}
