module "network" {
  source = "./modules/network"

  project            = var.project
  environment        = var.environment
  create_nat_gateway = var.create_nat_gateway
}

module "iam" {
  source = "./modules/iam"

  project            = var.project
  environment        = var.environment
  image_bucket_arn   = module.s3_bucket.bucket_arn
  image_bucket_name  = module.s3_bucket.bucket_name
  allow_ssm          = true
  ecr_repository_arn = module.ecr.repository_arn
  ecr_allowed_tag_prefixes = [
    "${var.environment}-*",
    var.environment
  ]
}

module "ecr" {
  source = "./modules/ecr"

  project         = var.project
  environment     = var.environment
  repository_name = var.ecr_repository_name
}

module "s3_bucket" {
  source = "./modules/s3_bucket"

  project           = var.project
  environment       = var.environment
  bucket_name       = var.image_bucket_name
  allowed_origins   = var.image_bucket_allowed_origins
  enable_versioning = var.environment == "prod" ? true : false
  prevent_destroy   = var.environment == "prod" ? true : false
  force_destroy     = var.environment == "prod" ? false : true
}

module "ec2" {
  source = "./modules/ec2"

  project              = var.project
  environment          = var.environment
  vpc_id               = module.network.vpc_id
  public_subnet_ids    = module.network.public_subnet_ids
  allowed_ssh_cidr     = var.allowed_ssh_cidr
  allowed_http_cidr    = var.allowed_http_cidr
  instance_type        = "t4g.small"
  ami_filter_name      = "ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-arm64-server-*"
  key_name             = var.ssh_key_name
  attach_eip           = true
  iam_instance_profile = module.iam.instance_profile_name
}

module "rds" {
  source = "./modules/rds"

  project                 = var.project
  environment             = var.environment
  vpc_id                  = module.network.vpc_id
  private_subnet_ids      = module.network.private_subnet_ids
  ec2_security_group_id   = module.ec2.security_group_id
  engine_version          = "16"
  instance_class          = "db.t4g.micro"
  allocated_storage       = var.rds_allocated_storage
  backup_retention_period = var.rds_backup_retention
  username                = var.rds_username
  password                = var.rds_password
  deletion_protection     = var.environment == "prod" ? true : false
}

data "tls_certificate" "github_actions" {
  count = var.github_oidc_provider_arn == "" ? 1 : 0
  url   = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_openid_connect_provider" "github_actions" {
  count = var.github_oidc_provider_arn == "" ? 1 : 0
  url   = "https://token.actions.githubusercontent.com"
  client_id_list = [
    "sts.amazonaws.com"
  ]
  thumbprint_list = [
    data.tls_certificate.github_actions[0].certificates[0].sha1_fingerprint
  ]
}

data "aws_iam_openid_connect_provider" "github_actions" {
  count = var.github_oidc_provider_arn == "" ? 0 : 1
  arn   = var.github_oidc_provider_arn
}

locals {
  github_oidc_provider_arn = var.github_oidc_provider_arn != "" ? var.github_oidc_provider_arn : aws_iam_openid_connect_provider.github_actions[0].arn
}

data "aws_iam_policy_document" "github_actions_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:ref:refs/heads/${var.github_branch}"]
    }
  }
}

resource "aws_iam_role" "github_actions" {
  name               = "${var.project}-${var.environment}-gha"
  assume_role_policy = data.aws_iam_policy_document.github_actions_assume.json
}

data "aws_iam_policy_document" "github_actions" {
  statement {
    sid    = "EcrAuth"
    effect = "Allow"
    actions = [
      "ecr:GetAuthorizationToken"
    ]
    resources = ["*"]
  }

  statement {
    sid    = "EcrPushPull"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:PutImage"
    ]
    resources = [module.ecr.repository_arn]
  }

  statement {
    sid    = "SsmSendCommand"
    effect = "Allow"
    actions = [
      "ssm:SendCommand",
      "ssm:GetCommandInvocation",
      "ssm:ListCommandInvocations"
    ]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "github_actions" {
  name   = "${var.project}-${var.environment}-gha-inline"
  policy = data.aws_iam_policy_document.github_actions.json
}

resource "aws_iam_role_policy_attachment" "github_actions" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.github_actions.arn
}
