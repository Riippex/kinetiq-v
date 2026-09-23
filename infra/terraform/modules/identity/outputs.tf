output "user_pool_id" {
  description = "ID of the Cognito User Pool"
  value       = aws_cognito_user_pool.main.id
}

output "user_pool_arn" {
  description = "ARN of the Cognito User Pool"
  value       = aws_cognito_user_pool.main.arn
}

output "user_pool_endpoint" {
  description = "Endpoint of the Cognito User Pool"
  value       = aws_cognito_user_pool.main.endpoint
}

output "issuer_url" {
  description = "OIDC Issuer URL for Cognito (used for MCP_OIDC_ISSUER)"
  value       = "https://${aws_cognito_user_pool.main.endpoint}"
}

output "jwks_url" {
  description = "JWKS URL for Cognito User Pool (used for MCP_OIDC_JWKS_URL)"
  value       = "https://${aws_cognito_user_pool.main.endpoint}/.well-known/jwks.json"
}

output "web_client_id" {
  description = "Client ID for the Web App"
  value       = aws_cognito_user_pool_client.web.id
}

output "mobile_client_id" {
  description = "Client ID for the Mobile App"
  value       = aws_cognito_user_pool_client.mobile.id
}

output "hosted_ui_domain" {
  description = "Cognito Hosted UI domain serving the OAuth authorization-code flow"
  value       = "${aws_cognito_user_pool_domain.main.domain}.auth.${data.aws_region.current.name}.amazoncognito.com"
}
