# ── modules/glue ─────────────────────────────────────────────────────────────
# The ingestion and feature engineering pipeline:
#
#   raw/customers/ (CSV) --crawler--> catalog table --transform--> processed/customers/ (Parquet)
#   processed/customers/ --feature-engineer--> features/customers/ (Parquet) + Feature Store
#
# Everything runs as the DataEngineer role. Both jobs run inside the private
# subnet through a Glue NETWORK connection and reach S3 and the Feature Store
# API through the NAT Gateway. The crawler does not need the VPC; it reads S3
# directly from the Glue service.

locals {
  name_prefix = "${var.project}-${var.environment}"

  # Glue catalog names may not contain hyphens.
  database_name = replace("${var.project}_${var.environment}", "-", "_")

  bucket_uri     = "s3://${var.bucket_name}"
  raw_path       = "${local.bucket_uri}/${var.raw_prefix}"
  processed_path = "${local.bucket_uri}/${var.processed_prefix}"
  features_path  = "${local.bucket_uri}/${var.features_prefix}"

  # Outside processed/customers/ on purpose: both jobs write their output with
  # mode("overwrite"), which would delete a temp dir nested inside it.
  temp_path = "${local.bucket_uri}/${var.temp_prefix}"
}

resource "aws_glue_catalog_database" "this" {
  name        = local.database_name
  description = "NorthStar ${var.environment} data catalog - tables discovered by the raw crawler"
}

# ── Network ──────────────────────────────────────────────────────────────────
# Glue refuses a NETWORK connection unless an attached security group allows
# all inbound traffic from itself: Spark workers talk to each other on
# arbitrary ports. A VPC-CIDR rule does not satisfy the check; the source has
# to be the group itself. Kept separate from the SageMaker security group,
# which is unchanged in Lab 2.
resource "aws_security_group" "glue" {
  name        = "${local.name_prefix}-${var.security_group_suffix}"
  description = "Glue job workers - self-referencing ingress for Spark, unrestricted egress via NAT"
  vpc_id      = var.vpc_id

  ingress {
    description = "All traffic between Glue workers in this group"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    self        = true
  }

  egress {
    description = "All outbound traffic - S3 and AWS APIs via the NAT Gateway"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.name_prefix}-${var.security_group_suffix}"
  }
}

resource "aws_glue_connection" "network" {
  name            = "${local.name_prefix}-${var.connection_suffix}"
  description     = "Places Glue job workers in the private subnet"
  connection_type = "NETWORK"

  physical_connection_requirements {
    availability_zone      = var.availability_zone
    subnet_id              = var.subnet_id
    security_group_id_list = [aws_security_group.glue.id]
  }
}

# ── Crawler ──────────────────────────────────────────────────────────────────
# No table_prefix: the table is named after the S3 prefix, so raw/customers/
# becomes "customers". On-demand only (no schedule).
resource "aws_glue_crawler" "raw" {
  name          = "${local.name_prefix}-${var.crawler_suffix}"
  description   = "Registers the schema of raw CSV files in the Glue catalog"
  database_name = aws_glue_catalog_database.this.name
  role          = var.role_arn

  s3_target {
    path = local.raw_path
  }
}

# ── Job scripts ──────────────────────────────────────────────────────────────
# Uploaded on apply. The etag makes Terraform re-upload when a script changes,
# so editing a script and re-applying is enough to deploy it.
resource "aws_s3_object" "transform_script" {
  bucket = var.bucket_name
  key    = "${var.scripts_prefix}${var.transform_script}"
  source = "${var.scripts_dir}/${var.transform_script}"
  etag   = filemd5("${var.scripts_dir}/${var.transform_script}")
}

resource "aws_s3_object" "feature_engineer_script" {
  bucket = var.bucket_name
  key    = "${var.scripts_prefix}${var.feature_engineer_script}"
  source = "${var.scripts_dir}/${var.feature_engineer_script}"
  etag   = filemd5("${var.scripts_dir}/${var.feature_engineer_script}")
}

# ── Jobs ─────────────────────────────────────────────────────────────────────

resource "aws_glue_job" "transform" {
  name              = "${local.name_prefix}-${var.transform_job_suffix}"
  description       = "raw/customers catalog table to typed, deduplicated Parquet in processed/customers"
  role_arn          = var.role_arn
  glue_version      = var.glue_version
  worker_type       = var.worker_type
  number_of_workers = var.number_of_workers
  timeout           = var.timeout_minutes
  connections       = [aws_glue_connection.network.name]

  command {
    name            = "glueetl"
    script_location = "${local.bucket_uri}/${aws_s3_object.transform_script.key}"
    python_version  = "3"
  }

  default_arguments = {
    "--TempDir"                          = local.temp_path
    "--enable-continuous-cloudwatch-log" = "true"
    "--database_name"                    = aws_glue_catalog_database.this.name
    "--table_name"                       = var.raw_table_name
    "--output_path"                      = local.processed_path
  }
}

resource "aws_glue_job" "feature_engineer" {
  name              = "${local.name_prefix}-${var.feature_engineer_job_suffix}"
  description       = "processed/customers to one labeled feature row per customer in features/customers and Feature Store"
  role_arn          = var.role_arn
  glue_version      = var.glue_version
  worker_type       = var.worker_type
  number_of_workers = var.number_of_workers
  timeout           = var.timeout_minutes
  connections       = [aws_glue_connection.network.name]

  command {
    name            = "glueetl"
    script_location = "${local.bucket_uri}/${aws_s3_object.feature_engineer_script.key}"
    python_version  = "3"
  }

  default_arguments = {
    "--TempDir"                          = local.temp_path
    "--enable-continuous-cloudwatch-log" = "true"
    "--input_path"                       = local.processed_path
    "--output_path"                      = local.features_path
    "--feature_group_name"               = var.feature_group_name
    "--region"                           = var.region
  }
}
