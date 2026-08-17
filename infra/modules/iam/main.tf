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

  # Absent unless an identity is passed in, the same shape as SSMAccess below.
  # A module consumer that does not send mail gets no ses:* at all rather than a
  # statement scoped to an empty ARN.
  dynamic "statement" {
    for_each = var.ses_identity_arn == "" ? [] : [1]
    content {
      sid    = "SesSendFromNoReply"
      effect = "Allow"
      # SendEmail only. SendRawEmail exists for hand-built MIME, which this app
      # does not produce, and it is the action that would let a caller forge
      # headers the condition below cannot see.
      actions = [
        "ses:SendEmail"
      ]
      # The identity, not "*". Scoped this way the instance can send as this
      # domain and nothing else in the account.
      resources = [var.ses_identity_arn]
      condition {
        # And within the domain, one address. Without this the role could send
        # as any local-part — including something that reads like a person, or
        # like the account owner — from a host that is exposed to the internet.
        test     = "StringEquals"
        variable = "ses:FromAddress"
        values   = [var.ses_from_address]
      }
    }
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
  lifecycle {
    precondition {
      # Without this the SES statement is still created, with the condition
      # "ses:FromAddress" = "" — which matches nothing, so every SendEmail is
      # denied. deliver_password_reset swallows that, so the user is answered
      # 202 and no mail is ever sent, with no error anywhere the operator looks.
      # Failing the plan is the only place this is cheap to notice.
      condition     = var.ses_identity_arn == "" || var.ses_from_address != ""
      error_message = "ses_from_address must be set whenever an SES identity is passed in; an empty one denies every send silently."
    }

    precondition {
      # SES authorises against the identity, so a sender outside the verified
      # domain is refused at send time — swallowed by deliver_password_reset,
      # so the user is answered 202 and nothing ever arrives. Same silent shape
      # as the empty address above, same reason to fail the plan instead.
      condition     = var.ses_domain == "" || endswith(var.ses_from_address, "@${var.ses_domain}")
      error_message = "ses_from_address must be under ses_domain; SES rejects a sender outside the verified identity."
    }
  }

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
