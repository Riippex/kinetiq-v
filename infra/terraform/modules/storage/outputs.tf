output "bucket_id" {
  description = "Name of the S3 media bucket"
  value       = aws_s3_bucket.media.id
}

output "bucket_arn" {
  description = "ARN of the S3 media bucket"
  value       = aws_s3_bucket.media.arn
}

output "bucket_domain_name" {
  description = "Regional domain name of the S3 media bucket"
  value       = aws_s3_bucket.media.bucket_regional_domain_name
}
