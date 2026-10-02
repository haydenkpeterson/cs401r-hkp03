# ── modules/iam ──────────────────────────────────────────────────────────────
# The identity model: three roles, each defined as much by what it cannot do
# as by what it can.
#
#   MLEngineer   - reads features/, writes artifacts/. Assumed by SageMaker.
#   DataEngineer - writes raw/, processed/, features/; cannot write artifacts/.
#                  Assumed by Glue, Lambda, and SageMaker (Feature Store).
#   ModelMonitor - reads artifacts/, writes CloudWatch metrics. Observes only.
#
# The S3 grants are deliberately split. Object actions are scoped to the
# artifacts/ and features/ prefixes; ListBucket is granted on the bucket ARN
# itself. Adding the bare bucket wildcard to the object statement would also
# match raw/* and processed/*, silently granting the write access this role is
# defined by NOT having.

locals {
  name_prefix             = "${var.project}-${var.environment}"
  role_name               = "${local.name_prefix}-${var.role_suffix}"
  data_engineer_role_name = "${local.name_prefix}-${var.data_engineer_role_suffix}"
  model_monitor_role_name = "${local.name_prefix}-${var.model_monitor_role_suffix}"
  bucket_prefix           = "arn:aws:s3:::${local.name_prefix}-data-*"
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

# ── DataEngineer ─────────────────────────────────────────────────────────────
# The data-plane identity: Glue crawlers and ETL jobs run as this role, and
# Feature Store uses it as the feature group's execution role.

resource "aws_iam_role" "data_engineer" {
  name        = local.data_engineer_role_name
  description = "Execution role for Glue crawlers and ETL jobs, Lambda ingestion, and the Feature Store offline store"

  # sagemaker.amazonaws.com is here only because CreateFeatureGroup rejects an
  # execution role that SageMaker cannot assume, and reports it as "The
  # execution role ARN is invalid" rather than naming the trust policy.
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = [
            "glue.amazonaws.com",
            "lambda.amazonaws.com",
            "sagemaker.amazonaws.com",
          ]
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Name = local.data_engineer_role_name
  }
}

resource "aws_iam_policy" "data_engineer" {
  name        = "${local.data_engineer_role_name}Policy"
  description = "Glue, Feature Store write, and S3 raw/processed/features access for the DataEngineer role"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # glue:* includes glue:GetConnection. Glue resolves the job's NETWORK
        # connection before the script runs, so without it the job fails at
        # provisioning with "DataCatalog Connection issue".
        Sid      = "GlueFull"
        Effect   = "Allow"
        Action   = ["glue:*"]
        Resource = "*"
      },
      {
        # Glue workers in the private subnet run on ENIs that Glue creates in
        # this account, as this role. The Describe calls are how Glue checks
        # the subnet, route table, and security group before it creates them.
        Sid    = "GlueVpcNetworkInterfaces"
        Effect = "Allow"
        Action = [
          "ec2:CreateNetworkInterface",
          "ec2:DeleteNetworkInterface",
          "ec2:Describe*",
        ]
        Resource = "*"
      },
      {
        # Glue tags every ENI it creates. Without this the job fails with
        # "doesn't have a permission to create a tag for your elastic network
        # interface".
        Sid      = "GlueNetworkInterfaceTags"
        Effect   = "Allow"
        Action   = ["ec2:CreateTags", "ec2:DeleteTags"]
        Resource = "arn:aws:ec2:*:*:network-interface/*"
      },
      {
        Sid      = "S3DataStages"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = [for prefix in var.data_engineer_writable_prefixes : "${local.bucket_prefix}/${prefix}*"]
      },
      {
        # The offline store writes objects with an ACL; plain PutObject is not
        # enough for it.
        Sid      = "S3FeatureStoreOfflineAcl"
        Effect   = "Allow"
        Action   = ["s3:PutObjectAcl"]
        Resource = "${local.bucket_prefix}/features/*"
      },
      {
        # Glue fetches its own job scripts from artifacts/glue/. Read only:
        # this role must never write artifacts/.
        Sid      = "S3GlueScriptsRead"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = [for prefix in var.data_engineer_readonly_prefixes : "${local.bucket_prefix}/${prefix}*"]
      },
      {
        # GetBucketAcl: Feature Store checks the bucket ACL before accepting it
        # as an offline store, and reports a missing grant as "Invalid S3Uri".
        Sid      = "S3BucketLevel"
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation", "s3:GetBucketAcl"]
        Resource = local.bucket_prefix
      },
      {
        Sid    = "FeatureStoreWrite"
        Effect = "Allow"
        Action = [
          "sagemaker:PutRecord",
          "sagemaker:CreateFeatureGroup",
          "sagemaker:DescribeFeatureGroup",
        ]
        Resource = "arn:aws:sagemaker:*:*:feature-group/*"
      },
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = [
          "arn:aws:logs:*:*:log-group:/aws-glue/*",
          "arn:aws:logs:*:*:log-group:/aws/lambda/*",
        ]
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "data_engineer" {
  role       = aws_iam_role.data_engineer.name
  policy_arn = aws_iam_policy.data_engineer.arn
}

# ── ModelMonitor ─────────────────────────────────────────────────────────────
# Watches, never acts. It can read drift results and raise alarms, but it
# cannot start a processing job, invoke an endpoint, or write to S3. Running
# the drift analysis is ModelMonitorExecution's job (Lab 6).

resource "aws_iam_role" "model_monitor" {
  name        = local.model_monitor_role_name
  description = "Read-only observer for drift results; publishes CloudWatch metrics and alarms"

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
    Name = local.model_monitor_role_name
  }
}

resource "aws_iam_policy" "model_monitor" {
  name        = "${local.model_monitor_role_name}Policy"
  description = "CloudWatch metrics and alarms, processing-job visibility, and read-only artifacts/ access"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # None of these four support resource-level permissions.
        Sid    = "CloudWatchMetricsAndAlarms"
        Effect = "Allow"
        Action = [
          "cloudwatch:PutMetricData",
          "cloudwatch:GetMetricStatistics",
          "cloudwatch:PutMetricAlarm",
          "cloudwatch:DescribeAlarms",
        ]
        Resource = "*"
      },
      {
        Sid      = "ProcessingJobVisibility"
        Effect   = "Allow"
        Action   = ["sagemaker:ListProcessingJobs", "sagemaker:DescribeProcessingJob"]
        Resource = "*"
      },
      {
        Sid      = "S3ArtifactsRead"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = [for prefix in var.model_monitor_readonly_prefixes : "${local.bucket_prefix}/${prefix}*"]
      },
      {
        Sid      = "CloudWatchLogs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:*:*:log-group:/aws/sagemaker/*"
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "model_monitor" {
  role       = aws_iam_role.model_monitor.name
  policy_arn = aws_iam_policy.model_monitor.arn
}
