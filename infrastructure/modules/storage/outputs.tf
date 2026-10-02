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

output "lifecycle_rule_ids" {
  description = "IDs of the lifecycle rules on the data bucket (empty when disabled)"
  value       = var.enable_lifecycle_rules ? [for r in aws_s3_bucket_lifecycle_configuration.data[0].rule : r.id] : []
}
