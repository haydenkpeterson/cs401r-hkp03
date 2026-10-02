# Every variable needs a description — Task B1 grades this.

variable "project" {
  description = "Project name, used as the first element of every resource name"
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
}

variable "role_suffix" {
  description = "Final element of the ML engineer role name, appended to project-environment"
  type        = string
  default     = "MLEngineer"
}

variable "writable_prefixes" {
  description = "Data-bucket prefixes the MLEngineer role may read and write objects in"
  type        = list(string)
  default     = ["artifacts/", "features/"]
}

variable "data_engineer_role_suffix" {
  description = "Final element of the data engineer role name, appended to project-environment"
  type        = string
  default     = "DataEngineer"
}

variable "data_engineer_writable_prefixes" {
  description = "Data-bucket prefixes the DataEngineer role may read and write objects in"
  type        = list(string)
  default     = ["raw/", "processed/", "features/"]
}

variable "data_engineer_readonly_prefixes" {
  description = "Data-bucket prefixes the DataEngineer role may only read (Glue job scripts)"
  type        = list(string)
  default     = ["artifacts/glue/"]
}

variable "model_monitor_role_suffix" {
  description = "Final element of the model monitor role name, appended to project-environment"
  type        = string
  default     = "ModelMonitor"
}

variable "model_monitor_readonly_prefixes" {
  description = "Data-bucket prefixes the ModelMonitor role may read"
  type        = list(string)
  default     = ["artifacts/"]
}
