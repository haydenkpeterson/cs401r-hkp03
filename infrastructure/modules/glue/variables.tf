# Every name in this module is derived from these variables; nothing is
# hardcoded in main.tf.

variable "project" {
  description = "Project name, used as the first element of every resource name"
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
}

variable "region" {
  description = "AWS region, passed to the feature engineering job for its Feature Store client"
  type        = string
}

# ── Wiring from other modules ────────────────────────────────────────────────

variable "bucket_name" {
  description = "Data bucket holding raw/, processed/, features/, and the job scripts under artifacts/"
  type        = string
}

variable "role_arn" {
  description = "IAM role the crawler and both jobs run as (DataEngineer)"
  type        = string
}

variable "vpc_id" {
  description = "VPC the Glue security group is created in"
  type        = string
}

variable "subnet_id" {
  description = "Private subnet the Glue job workers run in"
  type        = string
}

variable "availability_zone" {
  description = "Availability Zone of subnet_id; the Glue connection requires both to match"
  type        = string
}

variable "feature_group_name" {
  description = "Feature group the feature engineering job ingests into"
  type        = string
}

variable "scripts_dir" {
  description = "Local directory holding the Glue job scripts to upload"
  type        = string
}

# ── Names ────────────────────────────────────────────────────────────────────

variable "crawler_suffix" {
  description = "Crawler name suffix, appended to project-environment"
  type        = string
  default     = "raw-crawler"
}

variable "transform_job_suffix" {
  description = "Transform job name suffix, appended to project-environment"
  type        = string
  default     = "transform"
}

variable "feature_engineer_job_suffix" {
  description = "Feature engineering job name suffix, appended to project-environment"
  type        = string
  default     = "feature-engineer"
}

variable "connection_suffix" {
  description = "Glue NETWORK connection name suffix, appended to project-environment"
  type        = string
  default     = "glue-network"
}

variable "raw_table_name" {
  description = "Catalog table the crawler creates from raw_prefix (named after its last path element)"
  type        = string
  default     = "customers"
}

# ── S3 layout ────────────────────────────────────────────────────────────────

variable "raw_prefix" {
  description = "Prefix the crawler scans for raw CSV"
  type        = string
  default     = "raw/customers/"
}

variable "processed_prefix" {
  description = "Prefix the transform job writes Parquet to, and the feature job reads"
  type        = string
  default     = "processed/customers/"
}

variable "features_prefix" {
  description = "Prefix the feature engineering job writes Parquet to. Must differ from the Feature Store offline store prefix"
  type        = string
  default     = "features/customers/"
}

variable "temp_prefix" {
  description = "Glue --TempDir. Must be writable by the job role and outside every job output prefix"
  type        = string
  default     = "processed/_glue_temp/"
}

variable "scripts_prefix" {
  description = "Prefix job scripts are uploaded to; the role has read-only access here"
  type        = string
  default     = "artifacts/glue/"
}

variable "transform_script" {
  description = "File name of the transform job script in scripts_dir"
  type        = string
  default     = "transform.py"
}

variable "feature_engineer_script" {
  description = "File name of the feature engineering job script in scripts_dir"
  type        = string
  default     = "feature_engineer.py"
}

# ── Job sizing ───────────────────────────────────────────────────────────────

variable "glue_version" {
  description = "Glue runtime version"
  type        = string
  default     = "4.0"
}

variable "worker_type" {
  description = "Glue worker type for both jobs"
  type        = string
  default     = "G.1X"
}

variable "number_of_workers" {
  description = "Workers per job run. 2 is the G.1X minimum and plenty for ~160k rows"
  type        = number
  default     = 2
}

variable "timeout_minutes" {
  description = "Job timeout. Caps the cost of a run that hangs"
  type        = number
  default     = 30
}
