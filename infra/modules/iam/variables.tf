variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "image_bucket_arn" {
  type = string
}

variable "image_bucket_name" {
  type = string
}

variable "allow_ssm" {
  type    = bool
  default = true
}

variable "ecr_repository_arn" {
  type        = string
  description = "ECR repository ARN for tag-scoped access"
}

variable "ecr_allowed_tag_prefixes" {
  type        = list(string)
  description = "Allowed image tag patterns for this environment (e.g., [\"dev-*\", \"dev\"])"
  default     = ["*"]
}
