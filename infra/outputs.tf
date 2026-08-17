output "vpc_id" {
  value = module.network.vpc_id
}

output "public_subnets" {
  value = module.network.public_subnet_ids
}

output "private_subnets" {
  value = module.network.private_subnet_ids
}

output "ec2_public_ip" {
  value = module.ec2.public_ip
}

output "rds_endpoint" {
  value = module.rds.endpoint
}

output "ecr_repository_url" {
  value = module.ecr.repository_url
}

output "image_bucket_name" {
  value = module.s3_bucket.bucket_name
}

output "github_actions_role_arn" {
  value = aws_iam_role.github_actions.arn
}

# Read this straight after apply and paste the three rows into Cloudflare:
#   terraform output -json ses_dkim_cname_records
# Every row is DNS only (grey cloud). Proxying one leaves the identity Pending
# with nothing in the SES console explaining why.
output "ses_dkim_cname_records" {
  description = "CNAMEs to create in Cloudflare before SES will verify the domain"
  value       = try(one(module.ses[*].dkim_cname_records), [])
}

output "ses_verified_for_sending" {
  description = "Still false right after apply — SES only flips it once the CNAMEs resolve"
  value       = try(one(module.ses[*].verified_for_sending), null)
}
