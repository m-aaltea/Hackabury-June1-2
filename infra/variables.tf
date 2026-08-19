variable "region" {
  description = "AWS region for regional resources"
  type        = string
  default     = "eu-west-2"
}

variable "project_name" {
  description = "Short lowercase name used to prefix AWS resources"
  type        = string
  default     = "passpreview"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,30}$", var.project_name))
    error_message = "project_name must be 3-31 lowercase letters, numbers, or hyphens and start with a letter."
  }
}

variable "image_tag" {
  description = "Immutable backend image tag pushed by deploy.sh"
  type        = string
  default     = "bootstrap"
}

variable "lambda_architecture" {
  description = "Lambda CPU architecture; deploy.sh builds the matching image"
  type        = string
  default     = "arm64"

  validation {
    condition     = contains(["arm64", "x86_64"], var.lambda_architecture)
    error_message = "lambda_architecture must be arm64 or x86_64."
  }
}

variable "lambda_memory_mb" {
  description = "Memory allocated to FastAPI; CPU scales with this value"
  type        = number
  default     = 1024
}

variable "lambda_reserved_concurrency" {
  description = "Hard concurrency ceiling to limit accidental spend"
  type        = number
  default     = 5
}

variable "api_rate_limit" {
  description = "Steady requests per second accepted by API Gateway"
  type        = number
  default     = 2
}

variable "api_burst_limit" {
  description = "Short API Gateway request burst allowance"
  type        = number
  default     = 5
}

variable "log_retention_days" {
  description = "CloudWatch log retention"
  type        = number
  default     = 14
}
