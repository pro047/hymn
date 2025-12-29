variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "bucket_name" {
  type    = string
  default = ""
}

variable "allowed_origins" {
  description = "CORS allowed origins; leave empty to skip CORS"
  type        = list(string)
  default     = []
}

variable "enable_versioning" {
  type    = bool
  default = false
}
