variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "ap-northeast-2"
}

variable "project" {
  description = "Project prefix for naming"
  type        = string
  default     = "hymn"
}

variable "ecr_repository_name" {
  description = "Shared ECR repository name (leave empty to default to per-environment name)"
  type        = string
  default     = ""
}

variable "environment" {
  description = "Environment name (e.g., dev, prod)"
  type        = string
  default     = "dev"
}

variable "create_nat_gateway" {
  description = "Whether to create NAT Gateway and NAT EIP for private subnet egress"
  type        = bool
  default     = true
}

variable "github_repo" {
  description = "GitHub repo in owner/name format for OIDC trust policy"
  type        = string
  default     = "pro047/hymn"
}

variable "github_branch" {
  description = "GitHub branch allowed to assume OIDC role"
  type        = string
  default     = "develop"
}

variable "github_oidc_provider_arn" {
  description = "Existing GitHub Actions OIDC provider ARN (leave empty to create)"
  type        = string
  default     = ""
}

variable "allowed_ssh_cidr" {
  description = "CIDR blocks allowed to SSH to EC2"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "allowed_http_cidr" {
  description = "CIDR blocks allowed to HTTP/HTTPS"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "ssh_key_name" {
  description = "Existing EC2 key pair name"
  type        = string
}

variable "image_bucket_name" {
  description = "S3 bucket for images"
  type        = string
  default     = ""
}

variable "image_bucket_allowed_origins" {
  description = "Allowed origins for S3 CORS"
  type        = list(string)
  default     = []
}

variable "ses_domain" {
  description = "Domain to verify with SES for outbound mail (empty disables SES entirely)"
  type        = string
  default     = ""
}

variable "ses_from_address" {
  description = "The single From address the app may send as; must be under ses_domain"
  type        = string
  default     = ""

  validation {
    # Shape only — a variable validation cannot reference another variable, so
    # the domain match is a precondition in the iam module instead. It is not a
    # `check` block: those emit warnings and apply anyway, and every failure
    # mode here ends as a swallowed send rather than an error, so a warning is
    # exactly the wrong severity.
    condition     = var.ses_from_address == "" || can(regex("^[^@\\s]+@[^@\\s]+$", var.ses_from_address))
    error_message = "ses_from_address must be empty or a single address like no-reply@example.com."
  }
}

variable "rds_username" {
  description = "Master username for RDS"
  type        = string
  default     = "appuser"
}

variable "rds_password" {
  description = "Master password for RDS"
  type        = string
  sensitive   = true
}

variable "rds_allocated_storage" {
  description = "RDS storage in GB"
  type        = number
  default     = 20
}

variable "rds_backup_retention" {
  description = "RDS backup retention in days"
  type        = number
  default     = 7
}
