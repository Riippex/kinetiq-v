# Data source for AWS partition and region
data "aws_partition" "current" {}
data "aws_region" "current" {}

# ECS Task Execution Role (assumed by ECS container agent to pull images and configure logs/secrets)
resource "aws_iam_role" "ecs_execution_role" {
  name = "${var.project}-${var.environment}-ecs-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name        = "${var.project}-${var.environment}-ecs-execution-role"
    Environment = var.environment
    Project     = var.project
  }
}

resource "aws_iam_role_policy_attachment" "ecs_execution_managed" {
  role       = aws_iam_role.ecs_execution_role.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_policy" "ecs_execution_secrets" {
  name        = "${var.project}-${var.environment}-ecs-execution-secrets"
  description = "Scoped policy allowing ECS to retrieve specific secrets for container environments"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = var.secret_arns
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution_secrets" {
  role       = aws_iam_role.ecs_execution_role.name
  policy_arn = aws_iam_policy.ecs_execution_secrets.arn
}

# ECS Backend Task Role (assumed by the running Django application container)
resource "aws_iam_role" "backend_task_role" {
  name = "${var.project}-${var.environment}-backend-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name        = "${var.project}-${var.environment}-backend-task-role"
    Environment = var.environment
    Project     = var.project
  }
}

resource "aws_iam_policy" "backend_task_permissions" {
  name        = "${var.project}-${var.environment}-backend-task-policy"
  description = "Scoped permissions for Kinetiq backend (S3 photos, Bedrock, EventBridge)"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # Private S3 media access strictly scoped to photos/ prefix
      {
        Sid    = "ScopedMediaAccess"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:HeadObject"
        ]
        Resource = "${var.media_bucket_arn}/photos/*"
      },
      {
        Sid    = "ListMediaBucketPhotos"
        Effect = "Allow"
        Action = [
          "s3:ListBucket"
        ]
        Resource = var.media_bucket_arn
        Condition = {
          StringLike = {
            "s3:prefix" = ["photos/*"]
          }
        }
      },
      # Scoped Amazon Bedrock invocation for coaching routine generation
      {
        Sid    = "BedrockCoachingAccess"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel"
        ]
        Resource = [
          "arn:${data.aws_partition.current.partition}:bedrock:${data.aws_region.current.name}::foundation-model/anthropic.claude-3-haiku-20240307-v1:0",
          "arn:${data.aws_partition.current.partition}:bedrock:${data.aws_region.current.name}::foundation-model/amazon.nova-micro-v1:0"
        ]
      },
      # Scoped EventBridge publishing for transactional domain events
      {
        Sid    = "EventBridgePublishAccess"
        Effect = "Allow"
        Action = [
          "events:PutEvents"
        ]
        Resource = var.event_bus_arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "backend_task_policy" {
  role       = aws_iam_role.backend_task_role.name
  policy_arn = aws_iam_policy.backend_task_permissions.arn
}

# ECS Worker Task Role (assumed by the background worker and cleanup process)
resource "aws_iam_role" "worker_task_role" {
  name = "${var.project}-${var.environment}-worker-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name        = "${var.project}-${var.environment}-worker-task-role"
    Environment = var.environment
    Project     = var.project
  }
}

resource "aws_iam_policy" "worker_task_permissions" {
  name        = "${var.project}-${var.environment}-worker-task-policy"
  description = "Scoped permissions for Kinetiq background worker (S3 cleanup, SQS processing)"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # Private S3 media cleanup
      {
        Sid    = "ScopedMediaCleanup"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:DeleteObject",
          "s3:HeadObject"
        ]
        Resource = "${var.media_bucket_arn}/photos/*"
      },
      # SQS consumer permissions
      {
        Sid    = "SQSConsumerAccess"
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes"
        ]
        Resource = var.sqs_queue_arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "worker_task_policy" {
  role       = aws_iam_role.worker_task_role.name
  policy_arn = aws_iam_policy.worker_task_permissions.arn
}

# GitHub Actions OIDC Provider & Deployment Role
resource "aws_iam_openid_connect_provider" "github" {
  count = var.create_oidc_provider ? 1 : 0

  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1", "1c5824a80a67f6ec55bf0f34222b5e7e22a655b1"]

  tags = {
    Name        = "github-actions-oidc"
    Environment = var.environment
    Project     = var.project
  }
}

locals {
  oidc_provider_arn = var.create_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : var.existing_oidc_provider_arn
}

resource "aws_iam_role" "github_deployer" {
  name = "${var.project}-${var.environment}-github-deployer"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = local.oidc_provider_arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          }
          StringLike = {
            "token.actions.githubusercontent.com:sub" = "repo:${var.github_repository}:*"
          }
        }
      }
    ]
  })

  tags = {
    Name        = "${var.project}-${var.environment}-github-deployer"
    Environment = var.environment
    Project     = var.project
  }
}

resource "aws_iam_policy" "github_deployer_permissions" {
  name        = "${var.project}-${var.environment}-github-deployer-policy"
  description = "Least-privilege deployment permissions for GitHub Actions CI/CD"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # ECR push permissions scoped to backend and web repositories
      {
        Sid    = "ECRAuth"
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken"
        ]
        Resource = "*"
      },
      {
        Sid    = "ECRPush"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload"
        ]
        Resource = [
          var.backend_repository_arn,
          var.web_repository_arn
        ]
      },
      # ECS deployment permissions scoped to the cluster and services
      {
        Sid    = "ECSDeploy"
        Effect = "Allow"
        Action = [
          "ecs:UpdateService",
          "ecs:DescribeServices",
          "ecs:DescribeTaskDefinition",
          "ecs:RegisterTaskDefinition",
          "ecs:RunTask"
        ]
        Resource = "*"
      },
      # PassRole strictly scoped to the concrete task execution and task roles
      {
        Sid    = "ScopedPassRole"
        Effect = "Allow"
        Action = [
          "iam:PassRole"
        ]
        Resource = [
          aws_iam_role.ecs_execution_role.arn,
          aws_iam_role.backend_task_role.arn,
          aws_iam_role.worker_task_role.arn
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "github_deployer_policy" {
  role       = aws_iam_role.github_deployer.name
  policy_arn = aws_iam_policy.github_deployer_permissions.arn
}
