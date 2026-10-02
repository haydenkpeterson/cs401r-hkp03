# ── modules/feature_store ────────────────────────────────────────────────────
# One feature group: one labeled row per customer, written by the feature
# engineering Glue job and read by training jobs from Lab 3 onward.
#
#   Online store  - latest record per customer, for real-time inference.
#   Offline store - full history in S3 under features/offline-store/. Feature
#                   Store manages its own directory tree below that prefix, so
#                   it must not share a prefix with the Glue job's Parquet
#                   output in features/customers/.
#
# event_time is Fractional (Unix epoch seconds). Declared as String while the
# job sends a number, PutRecord still returns success but the record never
# reaches either store, with no error anywhere.

locals {
  name_prefix        = "${var.project}-${var.environment}"
  feature_group_name = "${local.name_prefix}-${var.feature_group_suffix}"
}

resource "aws_sagemaker_feature_group" "this" {
  feature_group_name             = local.feature_group_name
  description                    = "Customer churn features from the observation window, labeled from the outcome window"
  record_identifier_feature_name = var.record_identifier_feature_name
  event_time_feature_name        = var.event_time_feature_name

  # CreateFeatureGroup validates this role on the spot. A missing
  # sagemaker.amazonaws.com trust comes back as "execution role ARN is
  # invalid", and a missing s3:GetBucketAcl as "Invalid S3Uri".
  role_arn = var.role_arn

  dynamic "feature_definition" {
    for_each = var.feature_definitions
    content {
      feature_name = feature_definition.value.name
      feature_type = feature_definition.value.type
    }
  }

  online_store_config {
    enable_online_store = true
  }

  offline_store_config {
    s3_storage_config {
      s3_uri = "s3://${var.bucket_name}/${var.offline_store_prefix}"
    }
  }

  tags = {
    Name = local.feature_group_name
  }
}
