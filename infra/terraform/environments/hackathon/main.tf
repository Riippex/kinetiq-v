data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# Generate and store DJANGO_SECRET_KEY in Secrets Manager
resource "random_password" "django_secret_key" {
  length  = 50
  special = true
}

resource "aws_secretsmanager_secret" "django_secret_key" {
  name                    = "${var.project}/${var.environment}/django-secret-key"
  description             = "Cryptographic signing secret key for Django application"
  recovery_window_in_days = 0

  tags = {
    Environment = var.environment
    Project     = var.project
  }
}

resource "aws_secretsmanager_secret_version" "django_secret_key" {
  secret_id     = aws_secretsmanager_secret.django_secret_key.id
  secret_string = random_password.django_secret_key.result
}

# 1. Networking Module
module "networking" {
  source = "../../modules/networking"

  environment        = var.environment
  project            = var.project
  vpc_cidr           = var.vpc_cidr
  availability_zones = var.availability_zones
  single_nat_gateway = var.single_nat_gateway
}

# 2. Security Groups Module
module "security" {
  source = "../../modules/security"

  environment = var.environment
  project     = var.project
  vpc_id      = module.networking.vpc_id
}

# 3. Database Module (RDS PostgreSQL 17)
module "database" {
  source = "../../modules/database"

  environment       = var.environment
  project           = var.project
  subnet_ids        = module.networking.private_data_subnet_ids
  security_group_id = module.security.rds_security_group_id
}

# 4. Cache Module (ElastiCache Redis 7)
module "cache" {
  source = "../../modules/cache"

  environment       = var.environment
  project           = var.project
  subnet_ids        = module.networking.private_data_subnet_ids
  security_group_id = module.security.elasticache_security_group_id
}

# 5. Storage Module (Private S3 Media Bucket)
module "storage" {
  source = "../../modules/storage"

  environment = var.environment
  project     = var.project
  account_id  = data.aws_caller_identity.current.account_id
}

# 6. Identity Module (Cognito User Pool & Clients)
module "identity" {
  source = "../../modules/identity"

  environment = var.environment
  project     = var.project
}

# 7. ECR Module (Backend & Web Repositories)
module "ecr" {
  source = "../../modules/ecr"

  environment = var.environment
  project     = var.project
}

# 8. Messaging Module (EventBridge & SQS)
module "messaging" {
  source = "../../modules/messaging"

  environment = var.environment
  project     = var.project
}

# 9. Monitoring Module (CloudWatch Logs & AWS Budgets)
module "monitoring" {
  source = "../../modules/monitoring"

  environment                = var.environment
  project                    = var.project
  budget_limit_amount        = var.budget_limit_amount
  budget_notification_emails = var.budget_notification_emails
}

# 10. IAM Module (Least-Privilege Roles & GitHub OIDC)
module "iam" {
  source = "../../modules/iam"

  environment                = var.environment
  project                    = var.project
  media_bucket_arn           = module.storage.bucket_arn
  secret_arns                = [module.database.secret_arn, module.cache.secret_arn, aws_secretsmanager_secret.django_secret_key.arn]
  event_bus_arn              = module.messaging.event_bus_arn
  sqs_queue_arn              = module.messaging.workout_events_queue_arn
  backend_repository_arn     = module.ecr.backend_repository_arn
  web_repository_arn         = module.ecr.web_repository_arn
  ecs_cluster_arn            = module.compute.ecs_cluster_arn
  github_repository          = var.github_repository
  create_oidc_provider       = var.create_oidc_provider
  existing_oidc_provider_arn = var.existing_oidc_provider_arn
}

# 11. Compute Module (ECS Cluster, Fargate Services & ALB)
module "compute" {
  source = "../../modules/compute"

  environment                 = var.environment
  project                     = var.project
  vpc_id                      = module.networking.vpc_id
  public_subnet_ids           = module.networking.public_subnet_ids
  private_app_subnet_ids      = module.networking.private_app_subnet_ids
  alb_security_group_id       = module.security.alb_security_group_id
  ecs_tasks_security_group_id = module.security.ecs_tasks_security_group_id
  ecs_execution_role_arn      = module.iam.ecs_execution_role_arn
  backend_task_role_arn       = module.iam.backend_task_role_arn
  worker_task_role_arn        = module.iam.worker_task_role_arn
  backend_image               = "${module.ecr.backend_repository_url}:${var.backend_image_tag}"
  web_image                   = "${module.ecr.web_repository_url}:${var.web_image_tag}"
  media_bucket_id             = module.storage.bucket_id
  database_secret_arn         = module.database.secret_arn
  redis_secret_arn            = module.cache.secret_arn
  django_secret_key_arn       = aws_secretsmanager_secret.django_secret_key.arn
  cognito_issuer_url          = module.identity.issuer_url
  cognito_jwks_url            = module.identity.jwks_url
  cognito_web_client_id       = module.identity.web_client_id
  certificate_arn             = var.certificate_arn
  use_fargate_spot            = var.use_fargate_spot
}
