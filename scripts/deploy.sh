#!/usr/bin/env bash
# Deploy all services to ECR and force ECS to redeploy.
#
# Usage:
#   ./scripts/deploy.sh                  # deploy all services
#   ./scripts/deploy.sh orchestrator     # deploy one service
#
# Prerequisites: aws cli configured, docker running, jq installed.

set -euo pipefail

REGION="ap-southeast-1"
ACCOUNT_ID="026651348796"
CLUSTER="ai-router"
ECR_BASE="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

# Services that use the shared Dockerfile (root-level)
PIPELINE_SERVICES=(orchestrator bouncer classifier strategist adapters admin)
# Services with their own Dockerfile
SIDECAR_SERVICES=(presidio-sidecar)

TARGET="${1:-all}"

ecr_login() {
    echo "→ Logging in to ECR..."
    aws ecr get-login-password --region "${REGION}" \
        | docker login --username AWS --password-stdin "${ECR_BASE}"
}

build_and_push_pipeline() {
    local svc="$1"
    local repo="${ECR_BASE}/ai-router/${svc}"
    echo "→ Building ${svc}..."
    docker build \
        --build-arg SERVICE="${svc}" \
        --platform linux/amd64 \
        -t "${repo}:latest" \
        -f Dockerfile \
        .
    echo "→ Pushing ${svc}..."
    docker push "${repo}:latest"
}

build_and_push_presidio() {
    local repo="${ECR_BASE}/ai-router/presidio-sidecar"
    echo "→ Building presidio-sidecar..."
    docker build \
        --platform linux/amd64 \
        -t "${repo}:latest" \
        -f presidio_sidecar/Dockerfile \
        .
    echo "→ Pushing presidio-sidecar..."
    docker push "${repo}:latest"
}

redeploy_service() {
    local svc="$1"
    local ecs_svc="ai-router-${svc}"
    echo "→ Force redeploying ECS service ${ecs_svc}..."
    aws ecs update-service \
        --cluster "${CLUSTER}" \
        --service "${ecs_svc}" \
        --force-new-deployment \
        --region "${REGION}" \
        --output json \
        | jq -r '.service.serviceName + " → " + .service.status'
}

ecr_login

if [[ "${TARGET}" == "all" ]]; then
    for svc in "${PIPELINE_SERVICES[@]}"; do
        build_and_push_pipeline "${svc}"
    done
    build_and_push_presidio

    for svc in "${PIPELINE_SERVICES[@]}"; do
        redeploy_service "${svc}"
    done
    redeploy_service "presidio"

elif [[ "${TARGET}" == "presidio-sidecar" ]]; then
    build_and_push_presidio
    redeploy_service "presidio"

else
    build_and_push_pipeline "${TARGET}"
    redeploy_service "${TARGET}"
fi

echo ""
echo "✓ Deploy complete. Monitor progress:"
echo "  aws ecs describe-services --cluster ${CLUSTER} --services ai-router-orchestrator --region ${REGION}"
