output "identity_arn" {
  description = "ARN of the verified domain identity; the IAM policy scopes sending to it"
  value       = aws_sesv2_email_identity.domain.arn
}

output "verified_for_sending" {
  description = "False until the DKIM CNAMEs below are live in DNS and SES has checked them"
  value       = aws_sesv2_email_identity.domain.verified_for_sending_status
}

# The three records to create in Cloudflare, spelled out as name/value pairs
# rather than as raw tokens — the token alone is not what goes in the zone, and
# assembling it by hand is where this goes wrong.
#
# Every one of them must be DNS only (grey cloud). Proxying a CNAME makes
# Cloudflare answer with its own record, SES never sees the value it is looking
# for, and the identity sits at Pending forever with nothing in the console
# saying why.
output "dkim_cname_records" {
  description = "CNAME records to add in Cloudflare, DNS only (grey cloud), never proxied"
  value = [
    for token in aws_sesv2_email_identity.domain.dkim_signing_attributes[0].tokens : {
      name  = "${token}._domainkey.${var.domain}"
      value = "${token}.dkim.amazonses.com"
      proxy = "DNS only — do NOT enable the orange cloud"
    }
  ]
}
