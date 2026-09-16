# ── modules/iam ──────────────────────────────────────────────────────────────
# The identity model. In Lab 1 there is exactly one role: MLEngineer, assumed
# by SageMaker. Lab 2 adds DataEngineer and ModelMonitor once Glue, Lambda and
# CloudWatch are introduced.
#
# The S3 grants are deliberately split. Object actions are scoped to the
# artifacts/ and features/ prefixes; ListBucket is granted on the bucket ARN
# itself. Adding the bare bucket wildcard to the object statement would also
# match raw/* and processed/*, silently granting the write access this role is
# defined by NOT having.

locals {
  name_prefix   = "${var.project}-${var.environment}"
  role_name     = "${local.name_prefix}-${var.role_suffix}"
  bucket_prefix = "arn:aws:s3:::${local.name_prefix}-data-*"
}

resource "aws_iam_role" "ml_engineer" {
  name        = local.role_name
  description = "Execution role for SageMaker Studio and training jobs"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "sagemaker.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Name = local.role_name
  }
}

resource "aws_iam_policy" "ml_engineer" {
  name        = "${local.role_name}Policy"
  description = "Least-privilege permissions for the MLEngineer role"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SageMakerCore"
        Effect = "Allow"
        Action = [
          "sagemaker:CreateTrainingJob",
          "sagemaker:DescribeTrainingJob",
          "sagemaker:StopTrainingJob",
          "sagemaker:CreateEndpoint",
          "sagemaker:DescribeEndpoint",
          "sagemaker:DeleteEndpoint",
          "sagemaker:CreateEndpointConfig",
          "sagemaker:DeleteEndpointConfig",
          "sagemaker:CreateMlflowApp",
          "sagemaker:DescribeMlflowApp",
          "sagemaker:ListMlflowApps",
          "sagemaker:CreatePresignedMlflowAppUrl",
          "sagemaker:RegisterModel",
          "sagemaker:DescribeModelPackage",
          "sagemaker:ListModelPackages",
        ]
        Resource = "*"
      },
      {
        # Studio runs AS this role: opening the UI calls DescribeDomain,
        # ListApps and friends, and starting or stopping JupyterLab is
        # CreateApp / DeleteApp. Without this, Studio loads a blank page.
        # Scoped to Studio resource types only.
        Sid    = "StudioSelfService"
        Effect = "Allow"
        Action = [
          "sagemaker:DescribeDomain",
          "sagemaker:ListDomains",
          "sagemaker:DescribeUserProfile",
          "sagemaker:ListUserProfiles",
          "sagemaker:DescribeSpace",
          "sagemaker:ListSpaces",
          "sagemaker:CreateSpace",
          "sagemaker:UpdateSpace",
          "sagemaker:DeleteSpace",
          "sagemaker:DescribeApp",
          "sagemaker:ListApps",
          "sagemaker:CreateApp",
          "sagemaker:DeleteApp",
          "sagemaker:CreatePresignedDomainUrl",
        ]
        Resource = [
          "arn:aws:sagemaker:*:*:domain/*",
          "arn:aws:sagemaker:*:*:user-profile/*",
          "arn:aws:sagemaker:*:*:space/*",
          "arn:aws:sagemaker:*:*:app/*",
        ]
      },
      {
        Sid      = "S3ArtifactsAndFeatures"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = [for prefix in var.writable_prefixes : "${local.bucket_prefix}/${prefix}*"]
      },
      {
        Sid      = "S3BucketList"
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = local.bucket_prefix
      },
      {
        Sid      = "CloudWatchLogs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:*:*:log-group:/aws/sagemaker/*"
      },
      {
        Sid      = "ECRRead"
        Effect   = "Allow"
        Action   = ["ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage", "ecr:GetAuthorizationToken"]
        Resource = "*"
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ml_engineer" {
  role       = aws_iam_role.ml_engineer.name
  policy_arn = aws_iam_policy.ml_engineer.arn
}
