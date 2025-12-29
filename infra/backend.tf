terraform {
  required_version = ">= 1.5.7"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
  }

  backend "s3" {
    bucket         = "hymn-tfstate"
    key            = "global/terraform.tfstate"
    region         = "ap-northeast-2"
    dynamodb_table = "hymn-terraform-lock"
    encrypt        = true
  }
}
