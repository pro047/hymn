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
  default     = [
    "http://staging.score-hymn.com",
    "https://staging.score-hymn.com",
  ]
}

variable "enable_versioning" {
  type    = bool
  default = false
}

variable "prevent_destroy" {
  type    = bool
  default = true
}

variable "force_destroy" {
  type    = bool
  default = false
}
