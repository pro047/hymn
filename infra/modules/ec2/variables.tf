variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "public_subnet_ids" {
  type = list(string)
}

variable "allowed_ssh_cidr" {
  type = list(string)
}

variable "allowed_http_cidr" {
  type = list(string)
}

variable "instance_type" {
  type    = string
  default = "t4g.micro"
}

variable "ami_filter_name" {
  type    = string
  default = "ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-arm64-server-*"
}

variable "key_name" {
  type = string
}

variable "attach_eip" {
  type    = bool
  default = true
}

variable "iam_instance_profile" {
  type = string
}

variable "user_data" {
  type    = string
  default = ""
}
