environment        = "stg"
create_nat_gateway = false

ecr_repository_name = "hymn-api"
image_bucket_name   = "hymn-stg-images"
image_bucket_allowed_origins = [
  "https://www.score-hymn.com",
]

github_repo              = "pro047/hymn"
# deploys run from main since the pipeline rewire (2026-07)
github_branch            = "main"
github_oidc_provider_arn = "arn:aws:iam::989785488374:oidc-provider/token.actions.githubusercontent.com"
