locals {
  name_prefix = "${var.project}-${var.environment}"
}

# Domain identity rather than a single verified address. A single address would
# be verified in one click, but it pins the sender to whatever mailbox somebody
# happened to own and puts a personal address in front of every user. A domain
# identity signs with DKIM and lets the sender local-part change without another
# verification round.
#
# sesv2, not the v1 aws_ses_domain_identity: v1 needs a second resource
# (aws_ses_domain_dkim) to turn signing on, and the two can drift. v2 defaults to
# Easy DKIM when dkim_signing_attributes is omitted, so one resource carries both
# the identity and the signing config.
resource "aws_sesv2_email_identity" "domain" {
  email_identity = var.domain

  tags = {
    Name = "${local.name_prefix}-ses-domain"
  }
}

# A domain identity is unique per account *and region*, and this repo has a
# second root config — terraform.prod.tfvars — pointed at the same account and
# the same default region. Two consequences if that stack is ever applied with
# ses_domain set to score-hymn.com: its apply fails with AlreadyExists, and a
# `terraform destroy` here would take the identity the other stack depends on.
# Today the prod stack has no ses_domain (so no SES at all) and no workspace has
# ever been applied for it — `terraform workspace list` shows default/dev/stg —
# so this is a trap rather than a live conflict. If prod is ever stood up, the
# identity belongs in exactly one stack and the other should reference it.

# MAIL FROM is deliberately not configured. It would align SPF with the visible
# From address, which helps deliverability, but it costs an MX and a TXT record
# in Cloudflare on top of the three CNAMEs below. DKIM alone authenticates the
# mail; SPF alignment is worth adding only if bounces or spam placement are
# actually observed.
