# CloudWatch Log Groups for ECS tasks
resource "aws_cloudwatch_log_group" "backend" {
  name              = "/ecs/${var.project}-backend-${var.environment}"
  retention_in_days = var.log_retention_in_days

  tags = {
    Name        = "${var.project}-backend-logs"
    Environment = var.environment
    Project     = var.project
  }
}

resource "aws_cloudwatch_log_group" "web" {
  name              = "/ecs/${var.project}-web-${var.environment}"
  retention_in_days = var.log_retention_in_days

  tags = {
    Name        = "${var.project}-web-logs"
    Environment = var.environment
    Project     = var.project
  }
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/${var.project}-worker-${var.environment}"
  retention_in_days = var.log_retention_in_days

  tags = {
    Name        = "${var.project}-worker-logs"
    Environment = var.environment
    Project     = var.project
  }
}

resource "aws_cloudwatch_log_group" "migrate" {
  name              = "/ecs/${var.project}-migrate-${var.environment}"
  retention_in_days = var.log_retention_in_days

  tags = {
    Name        = "${var.project}-migrate-logs"
    Environment = var.environment
    Project     = var.project
  }
}

# AWS Budgets: proactive spend alert at $50/month
resource "aws_budgets_budget" "monthly" {
  name              = "${var.project}-monthly-budget-${var.environment}"
  budget_type       = "COST"
  limit_amount      = var.budget_limit_amount
  limit_unit        = "USD"
  time_unit         = "MONTHLY"
  time_period_start = "2026-09-01_00:00"

  dynamic "notification" {
    for_each = length(var.budget_notification_emails) > 0 ? [
      { threshold = 50, type = "ACTUAL" },
      { threshold = 80, type = "ACTUAL" },
      { threshold = 100, type = "ACTUAL" },
      { threshold = 100, type = "FORECASTED" }
    ] : []

    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value.threshold
      threshold_type             = "PERCENTAGE"
      notification_type          = notification.value.type
      subscriber_email_addresses = var.budget_notification_emails
    }
  }

  tags = {
    Name        = "${var.project}-budget-${var.environment}"
    Environment = var.environment
    Project     = var.project
  }
}
