environment        = "stg"
create_nat_gateway = false

ecr_repository_name = "hymn-api"
image_bucket_name   = "hymn-stg-images"
image_bucket_allowed_origins = [
  "http://staging.score-hymn.com",
  "https://staging.score-hymn.com",
]

github_repo              = "pro047/hymn"
github_branch            = "develop"
github_oidc_provider_arn = "arn:aws:iam::989785488374:oidc-provider/token.actions.githubusercontent.com"
