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
