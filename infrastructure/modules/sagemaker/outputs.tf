output "domain_id" {
  description = "ID of the SageMaker Domain"
  value       = aws_sagemaker_domain.this.id
}

output "domain_arn" {
  description = "ARN of the SageMaker Domain"
  value       = aws_sagemaker_domain.this.arn
}

output "domain_url" {
  description = "URL of the Studio Domain"
  value       = aws_sagemaker_domain.this.url
}

output "user_profile_name" {
  description = "Name of the Studio user profile"
  value       = aws_sagemaker_user_profile.this.user_profile_name
}
