output "ml_engineer_role_arn" {
  description = "ARN of the MLEngineer role — later labs pass this to SageMaker"
  value       = aws_iam_role.ml_engineer.arn
}

output "ml_engineer_role_name" {
  description = "Name of the MLEngineer role"
  value       = aws_iam_role.ml_engineer.name
}

output "ml_engineer_policy_arn" {
  description = "ARN of the inline-equivalent managed policy attached to the MLEngineer role"
  value       = aws_iam_policy.ml_engineer.arn
}

output "data_engineer_role_arn" {
  description = "ARN of the DataEngineer role - Glue jobs, crawlers, and the feature group run as it"
  value       = aws_iam_role.data_engineer.arn

  # The role exists before its policy is attached. CreateFeatureGroup checks
  # the role's permissions on the spot, so nothing may consume this ARN until
  # the attachment is in place.
  depends_on = [aws_iam_role_policy_attachment.data_engineer]
}

output "data_engineer_role_name" {
  description = "Name of the DataEngineer role"
  value       = aws_iam_role.data_engineer.name
}

output "model_monitor_role_arn" {
  description = "ARN of the ModelMonitor role"
  value       = aws_iam_role.model_monitor.arn
}

output "model_monitor_role_name" {
  description = "Name of the ModelMonitor role"
  value       = aws_iam_role.model_monitor.name
}
