#!/usr/bin/env bash
# Shared deploy logic for every environment. Not called directly — use
# deploy-{local,staging,production,gke}.sh. Applies, in order:
#   namespace -> secrets -> env overlay -> base manifests -> ingress overlay
#   -> digest-pinned images -> wait for rollout -> health check.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/game-k8s.defaults.sh"

ENV_NAME="${1:?usage: _deploy.sh <local|staging|production>}"
NS="${GAME_NAMESPACE:-$DEFAULT_NAMESPACE}"
IMAGE_TAG="${IMAGE_TAG:-$DEFAULT_IMAGE_TAG}"
K8S="$REPO_ROOT/k8s"
ENV_FILE="$K8S/env/${ENV_NAME}.yaml"

command -v kubectl >/dev/null 2>&1 || die "kubectl not found."
[ -f "$ENV_FILE" ] || die "Missing env overlay: $ENV_FILE"
assert_safe_image_tag "$IMAGE_TAG"

case "$ENV_NAME" in
  staging)    PUBLIC_HOST="$STAGING_PUBLIC_HOST" ;;
  production) PUBLIC_HOST="$PRODUCTION_PUBLIC_HOST" ;;
  *)          PUBLIC_HOST="" ;;
esac

log "Deploying ${GAME_ID} to '${ENV_NAME}' (namespace ${NS}, tag ${IMAGE_TAG})..."
info "Cluster context: $(kubectl config current-context)"

# 1. Namespace.
log "Applying namespace..."
kubectl apply -f "$K8S/base/namespace.yaml"

# 2. Secrets. Real ones are gitignored, so this expects the operator to have
#    copied the .example.yaml files and filled them in.
apply_secret() {
  local file="$K8S/secrets/$1" label="$2"
  if [ ! -f "$file" ]; then
    warn "No ${file} — copy the .example.yaml beside it and fill it in."
    return 1
  fi
  log "Applying ${label} secret..."
  # A real apply failure is a different problem from a missing file, and saying
  # "copy the example" at someone whose cluster just rejected the secret sends
  # them the wrong way.
  if ! sed 's/namespace: go-forth/namespace: '"$NS"'/g' "$file" | kubectl apply -n "$NS" -f -; then
    die "Applying ${file} failed. Fix the secret or your cluster credentials and retry."
  fi
}
apply_secret pg-dsn.yaml "database" || {
  warn "Without the database secret the API cannot start. Continuing so the rest applies."
}
# JoinQuest credentials are optional until JQ-188 consumes them.
apply_secret joinquest.yaml "JoinQuest credentials" || true

# 3. Env overlay (the two ConfigMaps the deployments read).
log "Applying ${ENV_NAME} ConfigMap overlay..."
kubectl apply -n "$NS" -f "$ENV_FILE"

# 4. TLS certificate, before the ingress that references its secret.
CERT_OVERLAY="$K8S/env/${ENV_NAME}-certificate.yaml"
if [ -f "$CERT_OVERLAY" ]; then
  log "Applying ${ENV_NAME} TLS certificate..."
  kubectl apply -f "$CERT_OVERLAY"
fi

# 5. Base workloads.
log "Applying base manifests..."
kubectl apply -n "$NS" -f "$K8S/base/postgres.yaml"
kubectl apply -n "$NS" -f "$K8S/base/api.yaml"
kubectl apply -n "$NS" -f "$K8S/base/client.yaml"
kubectl apply -n "$NS" -f "$K8S/base/ingress.yaml"

INGRESS_OVERLAY="$K8S/env/${ENV_NAME}-ingress.yaml"
if [ -f "$INGRESS_OVERLAY" ]; then
  log "Applying ${ENV_NAME} ingress overlay..."
  kubectl apply -n "$NS" -f "$INGRESS_OVERLAY"
fi

# 6. Pin images by digest — a mutable tag alone lets a cluster reuse a cached
#    layer from an earlier push of the same name.
REGISTRY="${REGISTRY:-docker.io}"
IMAGE_OWNER="${IMAGE_OWNER:-scruffyprodigy}"
API_TAG="${REGISTRY}/${IMAGE_OWNER}/${API_IMAGE_NAME}:${IMAGE_TAG}"
CLIENT_TAG="${REGISTRY}/${IMAGE_OWNER}/${CLIENT_IMAGE_NAME}:${IMAGE_TAG}"
API_IMAGE="$(resolve_image_digest "$API_TAG")"
CLIENT_IMAGE="$(resolve_image_digest "$CLIENT_TAG")"
pin_deployment_images "$NS" "$API_IMAGE" "$CLIENT_IMAGE"

# 7. Wait for rollout.
log "Waiting for deployments to become available..."
kubectl -n "$NS" rollout status deployment/go-forth-api --timeout=180s
kubectl -n "$NS" rollout status deployment/go-forth-client --timeout=180s

# 8. Prove it actually answers.
verify_deployed_health "$NS" "$PUBLIC_HOST"

ok "Deploy to '${ENV_NAME}' complete."
kubectl -n "$NS" get pods
