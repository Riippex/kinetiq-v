resource "random_password" "db_password" {
  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

# DB Subnet Group
resource "aws_db_subnet_group" "main" {
  name        = "${var.project}-${var.environment}-db-subnet-group"
  subnet_ids  = var.subnet_ids
  description = "Subnet group for private RDS PostgreSQL instances"

  tags = {
    Name        = "${var.project}-${var.environment}-db-subnet-group"
    Environment = var.environment
    Project     = var.project
  }
}

# DB Parameter Group enforcing SSL
resource "aws_db_parameter_group" "main" {
  name        = "${var.project}-${var.environment}-pg17-params"
  family      = "postgres17"
  description = "Custom parameter group for PostgreSQL 17 with forced SSL"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  tags = {
    Name        = "${var.project}-${var.environment}-pg17-params"
    Environment = var.environment
    Project     = var.project
  }
}

# RDS PostgreSQL Instance
resource "aws_db_instance" "main" {
  identifier                  = "${var.project}-${var.environment}-db"
  engine                      = "postgres"
  engine_version              = var.engine_version
  instance_class              = var.instance_class
  allocated_storage           = var.allocated_storage
  max_allocated_storage       = var.max_allocated_storage
  storage_type                = "gp3"
  storage_encrypted           = true
  multi_az                    = var.multi_az
  publicly_accessible         = false
  db_name                     = var.db_name
  username                    = var.db_username
  password                    = random_password.db_password.result
  db_subnet_group_name        = aws_db_subnet_group.main.name
  parameter_group_name        = aws_db_parameter_group.main.name
  vpc_security_group_ids      = [var.security_group_id]
  backup_retention_period     = var.backup_retention_period
  skip_final_snapshot         = var.skip_final_snapshot
  final_snapshot_identifier   = var.skip_final_snapshot ? null : "${var.project}-${var.environment}-db-final-snapshot"
  deletion_protection         = var.deletion_protection
  auto_minor_version_upgrade  = true
  allow_major_version_upgrade = false

  tags = {
    Name        = "${var.project}-${var.environment}-db"
    Environment = var.environment
    Project     = var.project
  }
}

# Secrets Manager Secret storing Database Credentials and DATABASE_URL
resource "aws_secretsmanager_secret" "db_credentials" {
  name                    = "${var.project}/${var.environment}/database"
  description             = "Connection credentials and DATABASE_URL for RDS PostgreSQL"
  recovery_window_in_days = 0

  tags = {
    Environment = var.environment
    Project     = var.project
  }
}

resource "aws_secretsmanager_secret_version" "db_credentials" {
  secret_id = aws_secretsmanager_secret.db_credentials.id
  secret_string = jsonencode({
    engine   = "postgres"
    host     = aws_db_instance.main.address
    port     = aws_db_instance.main.port
    dbname   = var.db_name
    username = var.db_username
    password = random_password.db_password.result
    # The generated password's special characters (#, %, &, ?, +, =, etc.)
    # are valid in a Secrets Manager string but not valid unescaped inside a
    # URI -- unescaped, they can break the URI's own delimiters (query
    # string, fragment, userinfo separator) or simply fail to parse.
    # urlencode() makes both the username and password components safe.
    database_url = "postgresql://${urlencode(var.db_username)}:${urlencode(random_password.db_password.result)}@${aws_db_instance.main.address}:${aws_db_instance.main.port}/${var.db_name}?sslmode=require"
  })
}
