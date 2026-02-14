variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "create_nat_gateway" {
  type    = bool
  default = true
}
