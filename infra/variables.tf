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
