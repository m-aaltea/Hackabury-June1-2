#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="${PROJECT_ROOT}/infra"
DEPLOY_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-${TF_VAR_region:-eu-west-2}}}"
LAMBDA_ARCH="${LAMBDA_ARCHITECTURE:-arm64}"

# Terraform's AWS SDK needs this enabled to read temporary credentials created
# by the modern browser-based `aws login` flow.
export AWS_SDK_LOAD_CONFIG=1

case "${LAMBDA_ARCH}" in
  arm64) DOCKER_PLATFORM="linux/arm64" ;;
  x86_64) DOCKER_PLATFORM="linux/amd64" ;;
  *) echo "LAMBDA_ARCHITECTURE must be arm64 or x86_64" >&2; exit 1 ;;
esac

for command_name in aws docker terraform npm; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "Missing required command: ${command_name}" >&2
    exit 1
  fi
done

# The browser-based `aws login` provider is newer than Terraform's AWS SDK.
# Export its short-lived credentials into this process only; do not print them
# or write them to disk.
if LOGIN_CREDENTIALS="$(aws configure export-credentials --format env 2>/dev/null)"; then
  eval "${LOGIN_CREDENTIALS}"
  unset LOGIN_CREDENTIALS
fi

aws sts get-caller-identity --region "${DEPLOY_REGION}" >/dev/null
docker info >/dev/null

echo "Building the frontend..."
npm --prefix "${PROJECT_ROOT}/frontend" ci
npm --prefix "${PROJECT_ROOT}/frontend" run build

cd "${INFRA_DIR}"
terraform init

# A Lambda image must exist before Terraform can create the function. On the
# first deployment only, create the Terraform-managed repository first.
if ! terraform state show aws_ecr_repository.backend >/dev/null 2>&1; then
  terraform apply \
    -target=aws_ecr_repository.backend \
    -target=aws_ecr_lifecycle_policy.backend \
    -var="region=${DEPLOY_REGION}"
fi

ECR_REPOSITORY="$(terraform output -raw ecr_repository_url)"
ECR_REGISTRY="${ECR_REPOSITORY%%/*}"
IMAGE_TAG="$(date -u +%Y%m%d%H%M%S)-$(git -C "${PROJECT_ROOT}" rev-parse --short HEAD 2>/dev/null || echo local)"
IMAGE_URI="${ECR_REPOSITORY}:${IMAGE_TAG}"

echo "Logging in to Amazon ECR..."
aws ecr get-login-password --region "${DEPLOY_REGION}" \
  | docker login --username AWS --password-stdin "${ECR_REGISTRY}"

echo "Building and pushing ${IMAGE_URI}..."
docker build \
  --platform "${DOCKER_PLATFORM}" \
  --provenance=false \
  --tag "${IMAGE_URI}" \
  "${PROJECT_ROOT}/backend"
docker push "${IMAGE_URI}"

echo "Applying the AWS infrastructure..."
terraform apply \
  -var="region=${DEPLOY_REGION}" \
  -var="lambda_architecture=${LAMBDA_ARCH}" \
  -var="image_tag=${IMAGE_TAG}"

GEMINI_PARAMETER_NAME="$(terraform output -raw gemini_parameter_name)"
if [[ -n "${GEMINI_API_KEY:-}" ]]; then
  echo "Saving the Gemini key as an encrypted SSM parameter..."
  aws ssm put-parameter \
    --region "${DEPLOY_REGION}" \
    --name "${GEMINI_PARAMETER_NAME}" \
    --type SecureString \
    --tier Standard \
    --value "${GEMINI_API_KEY}" \
    --overwrite >/dev/null
elif ! aws ssm get-parameter \
  --region "${DEPLOY_REGION}" \
  --name "${GEMINI_PARAMETER_NAME}" \
  --with-decryption >/dev/null 2>&1; then
  echo "Warning: GEMINI_API_KEY was not supplied; the backend will use fallback data." >&2
fi

FRONTEND_BUCKET="$(terraform output -raw frontend_bucket_name)"
DISTRIBUTION_ID="$(terraform output -raw cloudfront_distribution_id)"

echo "Uploading the frontend..."
aws s3 sync "${PROJECT_ROOT}/frontend/dist" "s3://${FRONTEND_BUCKET}" \
  --region "${DEPLOY_REGION}" \
  --delete \
  --exclude index.html \
  --cache-control "public,max-age=31536000,immutable"
aws s3 cp "${PROJECT_ROOT}/frontend/dist/index.html" "s3://${FRONTEND_BUCKET}/index.html" \
  --region "${DEPLOY_REGION}" \
  --cache-control "no-cache" \
  --content-type "text/html"

aws cloudfront create-invalidation \
  --distribution-id "${DISTRIBUTION_ID}" \
  --paths "/*" >/dev/null

echo
echo "Deployment complete: $(terraform output -raw app_url)"
