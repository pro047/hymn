module "network" {
  source = "./modules/network"

  project     = var.project
  environment = var.environment
}

module "iam" {
  source = "./modules/iam"

  project             = var.project
  environment         = var.environment
  image_bucket_arn    = module.s3_bucket.bucket_arn
  image_bucket_name   = module.s3_bucket.bucket_name
  allow_ssm           = true
}

module "ecr" {
  source = "./modules/ecr"

  project     = var.project
  environment = var.environment
}

module "s3_bucket" {
  source = "./modules/s3_bucket"

  project               = var.project
  environment           = var.environment
  bucket_name           = var.image_bucket_name
  allowed_origins       = var.image_bucket_allowed_origins
  enable_versioning     = var.environment == "prod" ? true : false
}

module "ec2" {
  source = "./modules/ec2"

  project                = var.project
  environment            = var.environment
  vpc_id                 = module.network.vpc_id
  public_subnet_ids      = module.network.public_subnet_ids
  allowed_ssh_cidr       = var.allowed_ssh_cidr
  allowed_http_cidr      = var.allowed_http_cidr
  instance_type          = "t4g.micro"
  ami_filter_name        = "ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-arm64-server-*"
  key_name               = var.ssh_key_name
  attach_eip             = true
  iam_instance_profile   = module.iam.instance_profile_name
}

module "rds" {
  source = "./modules/rds"

  project                  = var.project
  environment              = var.environment
  vpc_id                   = module.network.vpc_id
  private_subnet_ids       = module.network.private_subnet_ids
  ec2_security_group_id    = module.ec2.security_group_id
  engine_version           = "16"
  instance_class           = "db.t4g.micro"
  allocated_storage        = var.rds_allocated_storage
  backup_retention_period  = var.rds_backup_retention
  username                 = var.rds_username
  password                 = var.rds_password
  deletion_protection      = var.environment == "prod" ? true : false
}
