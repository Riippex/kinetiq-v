resource "aws_cognito_user_pool" "main" {
  name = "${var.project}-users-${var.environment}"

  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  password_policy {
    minimum_length    = 8
    require_lowercase = true
    require_numbers   = true
    require_symbols   = false
    require_uppercase = true
  }

  verification_message_template {
    default_email_option = "CONFIRM_WITH_CODE"
    email_subject        = "Your Kinetiq V verification code"
    email_message        = "Your verification code is {####}."
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  tags = {
    Name        = "${var.project}-users-${var.environment}"
    Environment = var.environment
    Project     = var.project
  }
}

# Resource server for API scopes (provides kinetiq/coach for Alexa+ MCP)
resource "aws_cognito_resource_server" "api" {
  identifier   = "kinetiq"
  name         = "Kinetiq API"
  user_pool_id = aws_cognito_user_pool.main.id

  scope {
    scope_name        = "coach"
    scope_description = "Access to Kinetiq coaching, routines, and sessions for Alexa+ MCP"
  }
}

# Web App Client
resource "aws_cognito_user_pool_client" "web" {
  name         = "${var.project}-client-web-${var.environment}"
  user_pool_id = aws_cognito_user_pool.main.id

  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile", "kinetiq/coach"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = var.web_callback_urls
  logout_urls                          = var.web_logout_urls

  prevent_user_existence_errors = "ENABLED"
  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH"
  ]

  depends_on = [aws_cognito_resource_server.api]
}

# Mobile App Client
resource "aws_cognito_user_pool_client" "mobile" {
  name         = "${var.project}-client-mobile-${var.environment}"
  user_pool_id = aws_cognito_user_pool.main.id

  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile", "kinetiq/coach"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = var.mobile_callback_urls
  logout_urls                          = var.mobile_logout_urls

  prevent_user_existence_errors = "ENABLED"
  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH"
  ]

  depends_on = [aws_cognito_resource_server.api]
}
