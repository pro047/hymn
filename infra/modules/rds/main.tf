locals {
  name_prefix = "${var.project}-${var.environment}"
}

resource "aws_db_subnet_group" "this" {
  name       = "${local.name_prefix}-rds-subnet"
  subnet_ids = var.private_subnet_ids

  tags = {
    Name = "${local.name_prefix}-rds-subnet"
  }
}

resource "aws_security_group" "rds" {
  name        = "${local.name_prefix}-rds-sg"
  description = "RDS access"
  vpc_id      = var.vpc_id

  ingress {
    from_port                = 5432
    to_port                  = 5432
    protocol                 = "tcp"
    security_groups          = [var.ec2_security_group_id]
    description              = "Postgres from EC2 SG"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.name_prefix}-rds-sg"
  }
}

resource "aws_db_parameter_group" "this" {
  name   = "${local.name_prefix}-pg"
  family = "postgres${replace(var.engine_version, ".", "")}"

  parameter {
    name  = "TimeZone"
    value = "Asia/Seoul"
  }
}

resource "aws_db_instance" "this" {
  identifier                  = "${local.name_prefix}-db"
  engine                      = "postgres"
  engine_version              = var.engine_version
  instance_class              = var.instance_class
  allocated_storage           = var.allocated_storage
  max_allocated_storage       = var.max_allocated_storage
  storage_type                = "gp3"
  db_subnet_group_name        = aws_db_subnet_group.this.name
  vpc_security_group_ids      = [aws_security_group.rds.id]
  username                    = var.username
  password                    = var.password
  port                        = 5432
  backup_retention_period     = var.backup_retention_period
  backup_window               = "03:00-04:00"
  maintenance_window          = "sun:04:00-sun:05:00"
  multi_az                    = false
  publicly_accessible         = false
  deletion_protection         = var.deletion_protection
  auto_minor_version_upgrade  = true
  performance_insights_enabled = false
  apply_immediately           = true
  skip_final_snapshot         = false
  final_snapshot_identifier   = "${local.name_prefix}-final"
  parameter_group_name        = aws_db_parameter_group.this.name

  tags = {
    Name = "${local.name_prefix}-db"
  }
}

output "endpoint" {
  value = aws_db_instance.this.endpoint
}

output "security_group_id" {
  value = aws_security_group.rds.id
}
