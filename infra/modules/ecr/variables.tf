variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "repository_name" {
  type        = string
  description = "Override repository name (shared across envs); defaults to project-environment-api"
  default     = ""
}
