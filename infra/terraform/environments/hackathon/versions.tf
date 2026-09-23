terraform {
  # >= 1.9.0: variable validation conditions in this configuration
  # (certificate_arn's, referencing domain_name) reference another
  # variable, which Terraform only supports as of 1.9. CI pins an exact
  # 1.10.5 already; this floor just makes the real constraint honest.
  required_version = ">= 1.9.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}
