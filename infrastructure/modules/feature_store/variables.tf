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

variable "bucket_name" {
  description = "Data bucket that backs the offline store"
  type        = string
}

variable "role_arn" {
  description = "Execution role for the feature group (DataEngineer). Must trust sagemaker.amazonaws.com"
  type        = string
}

variable "feature_group_suffix" {
  description = "Feature group name suffix, appended to project-environment"
  type        = string
  default     = "customer-features"
}

variable "offline_store_prefix" {
  description = "Prefix for the offline store. Kept apart from the Glue job's features/customers/ output"
  type        = string
  default     = "features/offline-store/"
}

variable "record_identifier_feature_name" {
  description = "Feature that uniquely identifies a record"
  type        = string
  default     = "customer_id"
}

variable "event_time_feature_name" {
  description = "Feature holding the record's event time. Must be declared Fractional in feature_definitions"
  type        = string
  default     = "event_time"
}

# Order matches the Architecture Reference: 2 keys, 13 features, 1 label.
variable "feature_definitions" {
  description = "Feature names and types (String, Fractional, or Integral)"
  type = list(object({
    name = string
    type = string
  }))
  default = [
    # keys
    { name = "customer_id", type = "String" },
    { name = "event_time", type = "Fractional" },
    # features - all computed from the observation window (on or before T)
    { name = "days_since_last_purchase", type = "Fractional" },
    { name = "customer_tenure_days", type = "Fractional" },
    { name = "purchase_frequency_30d", type = "Fractional" },
    { name = "purchase_frequency_90d", type = "Fractional" },
    { name = "purchase_frequency_180d", type = "Fractional" },
    { name = "avg_order_value", type = "Fractional" },
    { name = "total_spend_90d", type = "Fractional" },
    { name = "total_lifetime_value", type = "Fractional" },
    { name = "avg_basket_size_6m", type = "Fractional" },
    { name = "category_diversity_score", type = "Fractional" },
    { name = "online_to_store_ratio", type = "Fractional" },
    { name = "loyalty_tier", type = "String" },
    { name = "churn_risk_score", type = "Fractional" },
    # label - from the outcome window only
    { name = "churn_label", type = "Integral" },
  ]

  validation {
    condition     = alltrue([for f in var.feature_definitions : contains(["String", "Fractional", "Integral"], f.type)])
    error_message = "Each feature type must be String, Fractional, or Integral."
  }
}
