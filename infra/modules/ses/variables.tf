variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "domain" {
  type        = string
  description = "Domain to verify as a sending identity (e.g. score-hymn.com)"
}
