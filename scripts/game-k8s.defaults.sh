# Game-specific Kubernetes defaults — sourced by scripts/_deploy.sh.
# Override via the environment when deploying somewhere other than the default.
GAME_ID="${GAME_ID:-go-forth}"
# An explicit per-game tag, never :latest — the demo games share a registry
# owner, and a :latest push from one has landed in another's cluster before.
DEFAULT_IMAGE_TAG="${DEFAULT_IMAGE_TAG:-go-forth}"
API_IMAGE_NAME="${API_IMAGE_NAME:-go-forth-api}"
CLIENT_IMAGE_NAME="${CLIENT_IMAGE_NAME:-go-forth-client}"
DEFAULT_NAMESPACE="${DEFAULT_NAMESPACE:-go-forth}"
# Public hosts per environment, kept in step with k8s/env/<env>-ingress.yaml.
# Both are placeholders until a domain is registered and DNS points at the
# ingress controller — see the header of k8s/env/production.yaml.
STAGING_PUBLIC_HOST="${STAGING_PUBLIC_HOST:-go-forth.staging.joinquest.cc}"
PRODUCTION_PUBLIC_HOST="${PRODUCTION_PUBLIC_HOST:-go-forth.example}"
