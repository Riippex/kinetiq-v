# Data source for AWS partition, region and account
data "aws_partition" "current" {}
data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

locals {
  # Deterministic ARN patterns (family names are plain strings computed from
  # project/environment, not real Terraform resource attributes), so IAM
  # scoping here never depends on the compute module's actual task
  # definitions -- avoiding a module cycle (compute already depends on this
  # module for its task/execution role ARNs).
  worker_task_family_arn = "arn:${data.aws_partition.current.partition}:ecs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:task-definition/${var.project}-worker-${var.environment}:*"
  ecs_cluster_arn        = "arn:${data.aws_partition.current.partition}:ecs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:cluster/${var.project}-${var.environment}-cluster"
  # EventBridge Scheduler schedules that don't specify a group live in the
  # "default" group -- matches aws_scheduler_schedule.media_cleanup in the
  # compute module, which does not set group_name.
  media_cleanup_schedule_arn = "arn:${data.aws_partition.current.partition}:scheduler:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:schedule/default/${var.project}-media-cleanup-${var.environment}"

  github_owner     = split("/", var.github_repository)[0]
  github_repo_name = split("/", var.github_repository)[1]

  # Environment-scoped immutable OIDC subject: GitHub's numeric owner and
  # repository IDs are permanent even if the repository (or its owner
  # account) is later renamed or transferred, unlike the plain
  # "repo:<owner>/<repo>:..." name-based subject, which would silently
  # start matching a *different* repository that later claims the old
  # name. var.github_repository_id / var.github_repository_owner_id are
  # required (see variables.tf) -- there is no name-only fallback.
  github_oidc_subject = "repo:${local.github_owner}@${var.github_repository_owner_id}/${local.github_repo_name}@${var.github_repository_id}:environment:${var.github_oidc_environment}"
}

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
          # s3:GetObject already authorizes HeadObject requests against the
          # same key; "s3:HeadObject" is not a real IAM action name.
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject"
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
          # s3:GetObject already authorizes HeadObject; not a real IAM action.
          "s3:GetObject",
          "s3:DeleteObject"
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
          # Exact match only: this role is assumable only by a workflow run
          # that went through the `github_oidc_environment` GitHub
          # Environment (which itself can require a manual reviewer
          # approval before the job runs) -- never by any workflow run on
          # any branch/PR/tag in the repository, which is what the former
          # "repo:...:*" wildcard allowed.
          #
          # Environment-scoped immutable subject (local.github_oidc_subject):
          # repo:<owner>@<owner-id>/<repo>@<repo-id>:environment:<environment>.
          # Uses GitHub's numeric owner/repository IDs, not just names, so
          # the trust survives (and does not silently start matching a
          # different repository after) a rename or ownership transfer.
          # var.github_repository_id / var.github_repository_owner_id are
          # required inputs (see variables.tf) -- there is no name-only
          # fallback. Terraform can only verify these look like numeric
          # IDs, not that they are genuinely this repository's; see
          # "GitHub OIDC immutable subject" in
          # docs/runbooks/infrastructure-bootstrap.md for how to retrieve
          # and independently confirm the real values before relying on
          # this role.
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
            "token.actions.githubusercontent.com:sub" = local.github_oidc_subject
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
      # ECS deployment permissions. RegisterTaskDefinition/DescribeTaskDefinition
      # do not support resource-level scoping (AWS requires Resource "*" for
      # them); UpdateService/RunTask/DescribeServices/DescribeTasks are
      # further bounded below to this one cluster via an ecs:cluster
      # condition, so this role can never touch a cluster it doesn't own.
      {
        Sid    = "ECSTaskDefinitions"
        Effect = "Allow"
        Action = [
          "ecs:RegisterTaskDefinition",
          "ecs:DescribeTaskDefinition"
        ]
        Resource = "*"
      },
      {
        Sid    = "ECSDeployBoundToCluster"
        Effect = "Allow"
        Action = [
          "ecs:UpdateService",
          "ecs:DescribeServices",
          "ecs:RunTask",
          "ecs:DescribeTasks"
        ]
        Resource = "*"
        Condition = {
          ArnEquals = {
            "ecs:cluster" = local.ecs_cluster_arn
          }
        }
      },
      # Read-only, unscopable-by-resource lookups the migration task's
      # network configuration needs -- describe/list actions never support
      # resource-level ARNs in IAM. The post-deploy health check hits the
      # canonical HTTPS domain directly (see verify in deploy.yml) and
      # needs no AWS API calls at all, so no elasticloadbalancing
      # permission is granted here.
      {
        Sid    = "DeployWorkflowReadOnlyLookups"
        Effect = "Allow"
        Action = [
          "ec2:DescribeSubnets",
          "ec2:DescribeSecurityGroups"
        ]
        Resource = "*"
      },
      # Repoint the media-cleanup schedule at the worker task definition
      # revision just registered for the newly deployed image -- otherwise
      # the schedule keeps running whatever image was current at the last
      # `terraform apply`, not the image this workflow run just deployed.
      # Scoped to exactly this one schedule.
      {
        Sid    = "UpdateMediaCleanupSchedule"
        Effect = "Allow"
        Action = [
          "scheduler:GetSchedule",
          "scheduler:UpdateSchedule"
        ]
        Resource = local.media_cleanup_schedule_arn
      },
      # PassRole strictly scoped to the concrete task execution and task
      # roles, plus the scheduler execution role -- required because
      # scheduler:UpdateSchedule's request includes the target's RoleArn
      # (unchanged, but AWS still checks PassRole for it on every update).
      {
        Sid    = "ScopedPassRole"
        Effect = "Allow"
        Action = [
          "iam:PassRole"
        ]
        Resource = [
          aws_iam_role.ecs_execution_role.arn,
          aws_iam_role.backend_task_role.arn,
          aws_iam_role.worker_task_role.arn,
          aws_iam_role.scheduler_execution_role.arn
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "github_deployer_policy" {
  role       = aws_iam_role.github_deployer.name
  policy_arn = aws_iam_policy.github_deployer_permissions.arn
}

# EventBridge Scheduler execution role: runs the one-shot media-cleanup ECS
# task on a recurring schedule, in place of a continuously-restarting ECS
# Service (which would crash-loop forever, since the command it runs always
# exits). Scoped to exactly one task definition family and this cluster.
resource "aws_iam_role" "scheduler_execution_role" {
  name = "${var.project}-${var.environment}-scheduler-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "scheduler.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name        = "${var.project}-${var.environment}-scheduler-execution-role"
    Environment = var.environment
    Project     = var.project
  }
}

resource "aws_iam_policy" "scheduler_execution_permissions" {
  name        = "${var.project}-${var.environment}-scheduler-execution-policy"
  description = "Scoped permissions for EventBridge Scheduler to run the media-cleanup task"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "RunWorkerTaskOnThisCluster"
        Effect   = "Allow"
        Action   = ["ecs:RunTask"]
        Resource = [local.worker_task_family_arn]
        Condition = {
          ArnEquals = {
            "ecs:cluster" = local.ecs_cluster_arn
          }
        }
      },
      {
        Sid    = "PassWorkerAndExecutionRoles"
        Effect = "Allow"
        Action = ["iam:PassRole"]
        Resource = [
          aws_iam_role.ecs_execution_role.arn,
          aws_iam_role.worker_task_role.arn
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "scheduler_execution_policy" {
  role       = aws_iam_role.scheduler_execution_role.name
  policy_arn = aws_iam_policy.scheduler_execution_permissions.arn
}
