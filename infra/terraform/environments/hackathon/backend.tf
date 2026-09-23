# Remote state configuration in S3 with native S3 locking (use_lockfile = true, supported in Terraform 1.10+)
# Bootstrap instructions for this bucket are documented in docs/runbooks/aws-deployment-costs.md.
terraform {
  backend "s3" {
    bucket       = "kinetiq-v-terraform-state-hackathon"
    key          = "environments/hackathon/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
