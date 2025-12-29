#!/usr/bin/env bash
set -euo pipefail

# Usage: ./scripts/ecr_login_and_push.sh <repo_name> <tag>
# Example: ./scripts/ecr_login_and_push.sh hymn-dev-api $(git rev-parse --short HEAD)

AWS_REGION="${AWS_REGION:-ap-northeast-2}"
ACCOUNT_ID="${ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"
REPO_NAME="${1:-}"
TAG="${2:-}"

if [[ -z "$REPO_NAME" || -z "$TAG" ]]; then
  echo "Usage: $0 <repo_name> <tag>" >&2
  exit 1
fi

IMAGE="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${REPO_NAME}:${TAG}"

echo "Logging in to ECR: ${AWS_REGION}"
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

echo "Building image: ${IMAGE}"
docker build -t "${IMAGE}" -f Dockerfile .

echo "Pushing image: ${IMAGE}"
docker push "${IMAGE}"

echo "Done. Image pushed: ${IMAGE}"
