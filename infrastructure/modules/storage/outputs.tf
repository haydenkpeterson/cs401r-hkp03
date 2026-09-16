output "bucket_name" {
  description = "Name of the data bucket"
  value       = aws_s3_bucket.data.id
}

output "bucket_arn" {
  description = "ARN of the data bucket"
  value       = aws_s3_bucket.data.arn
}

output "prefixes" {
  description = "Top-level prefixes created in the data bucket"
  value       = [for obj in aws_s3_object.prefixes : obj.key]
}
