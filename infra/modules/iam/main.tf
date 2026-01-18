locals {
  name_prefix = "${var.project}-${var.environment}"
}

data "aws_iam_policy_document" "assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ec2" {
  name               = "${local.name_prefix}-ec2-role"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
}

data "aws_iam_policy_document" "inline" {
  statement {
    sid    = "EcrPull"
    effect = "Allow"
    actions = [
      "ecr:GetAuthorizationToken"
    ]
    resources = ["*"]
  }

  statement {
    sid    = "EcrPullScoped"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage"
    ]
    resources = [var.ecr_repository_arn]
    condition {
      test     = "StringLikeIfExists"
      variable = "ecr:ImageTag"
      values   = var.ecr_allowed_tag_prefixes
    }
  }

  statement {
    sid    = "ImageBucketAccess"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:ListBucket"
    ]
    resources = [
      var.image_bucket_arn,
      "${var.image_bucket_arn}/*"
    ]
  }

  dynamic "statement" {
    for_each = var.allow_ssm ? [1] : []
    content {
      sid    = "SSMAccess"
      effect = "Allow"
      actions = [
        "ssm:DescribeAssociation",
        "ssm:GetDeployablePatchSnapshotForInstance",
        "ssm:GetDocument",
        "ssm:DescribeDocument",
        "ssm:GetManifest",
        "ssm:GetParameter",
        "ssm:GetParameters",
        "ssm:ListAssociations",
        "ssm:ListInstanceAssociations",
        "ssm:PutInventory",
        "ssm:PutComplianceItems",
        "ssm:PutConfigurePackageResult",
        "ssm:UpdateAssociationStatus",
        "ssm:UpdateInstanceAssociationStatus",
        "ssm:UpdateInstanceInformation",
        "ssmmessages:CreateControlChannel",
        "ssmmessages:CreateDataChannel",
        "ssmmessages:OpenControlChannel",
        "ssmmessages:OpenDataChannel",
        "ec2messages:AcknowledgeMessage",
        "ec2messages:DeleteMessage",
        "ec2messages:FailMessage",
        "ec2messages:GetEndpoint",
        "ec2messages:GetMessages",
        "ec2messages:SendReply"
      ]
      resources = ["*"]
    }
  }
}

resource "aws_iam_policy" "inline" {
  name   = "${local.name_prefix}-ec2-inline"
  policy = data.aws_iam_policy_document.inline.json
}

resource "aws_iam_role_policy_attachment" "attach_inline" {
  role       = aws_iam_role.ec2.name
  policy_arn = aws_iam_policy.inline.arn
}

resource "aws_iam_instance_profile" "ec2" {
  name = "${local.name_prefix}-ec2-profile"
  role = aws_iam_role.ec2.name
}

output "role_name" {
  value = aws_iam_role.ec2.name
}

output "instance_profile_name" {
  value = aws_iam_instance_profile.ec2.name
}
