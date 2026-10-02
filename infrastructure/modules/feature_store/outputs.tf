output "feature_group_name" {
  description = "Name of the customer feature group"
  value       = aws_sagemaker_feature_group.this.feature_group_name
}

output "feature_group_arn" {
  description = "ARN of the customer feature group"
  value       = aws_sagemaker_feature_group.this.arn
}

output "offline_store_s3_uri" {
  description = "S3 URI backing the offline store"
  value       = aws_sagemaker_feature_group.this.offline_store_config[0].s3_storage_config[0].s3_uri
}
