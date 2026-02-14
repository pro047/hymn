environment        = "prod"
create_nat_gateway = false
allowed_ssh_cidr   = ["222.105.45.74/32"]

ecr_repository_name = "hymn-prod-api"
image_bucket_name   = "hymn-prod-images"
image_bucket_allowed_origins = [
  "http://score-hymn.com",
  "https://score-hymn.com",
]

github_repo              = "pro047/hymn"
github_branch            = "main"
github_oidc_provider_arn = "arn:aws:iam::989785488374:oidc-provider/token.actions.githubusercontent.com"
