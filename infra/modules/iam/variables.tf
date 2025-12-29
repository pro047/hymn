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
