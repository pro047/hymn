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

variable "ses_identity_arn" {
  type        = string
  description = "Verified SES identity to allow sending from. Empty grants no SES access at all."
  default     = ""
}

variable "ses_from_address" {
  type        = string
  description = "The only From address the instance may send as. Enforced as an IAM condition."
  default     = ""
}

variable "ses_domain" {
  type        = string
  description = <<-EOT
    The verified domain, passed in only so the precondition below can check that
    ses_from_address belongs to it. It is already inside ses_identity_arn, but
    that ARN is unknown at plan time on a first apply, and an assertion that
    defers to apply fails halfway through one.
  EOT
  default     = ""
}
