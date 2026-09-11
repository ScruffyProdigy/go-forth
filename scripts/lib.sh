#!/usr/bin/env bash
# Shared helpers for the Go Forth! scripts: colored output, port checks, env
# loading, a docker-compose wrapper, and the image-pinning helpers the deploy
# scripts use. Source it:  source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

set -euo pipefail

# ---- Colors (disabled when not a TTY) ---------------------------------------
if [ -t 1 ]; then
  C_RESET="\033[0m"; C_RED="\033[0;31m"; C_GREEN="\033[0;32m"
  C_YELLOW="\033[0;33m"; C_BLUE="\033[0;34m"; C_CYAN="\033[0;36m"; C_BOLD="\033[1m"
else
  C_RESET=""; C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""; C_CYAN=""; C_BOLD=""
fi

log()   { printf "${C_CYAN}▶${C_RESET} %s\n" "$*" >&2; }
info()  { printf "${C_BLUE}ℹ${C_RESET} %s\n" "$*" >&2; }
ok()    { printf "${C_GREEN}✓${C_RESET} %s\n" "$*" >&2; }
warn()  { printf "${C_YELLOW}⚠${C_RESET} %s\n" "$*" >&2; }
err()   { printf "${C_RED}✗ %s${C_RESET}\n" "$*" >&2; }
die()   { err "$*"; exit 1; }

# Repo root = parent of the scripts directory.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ---- Load .env (if present) into the environment ----------------------------
load_env() {
  if [ -f "$REPO_ROOT/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    . "$REPO_ROOT/.env"
    set +a
  else
    warn ".env not found — using the defaults from .env.example"
  fi
  # Defaults, kept in step with .env.example and api/src/config.ts.
  : "${API_PORT:=3002}"
  : "${CLIENT_PORT:=5175}"
  : "${POSTGRES_PORT:=5434}"
  : "${POSTGRES_HOST:=localhost}"
  : "${POSTGRES_USER:=goforth}"
  : "${POSTGRES_PASSWORD:=goforth_dev_password}"
  : "${POSTGRES_DB:=go_forth}"
  : "${DATABASE_URL:=postgres://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}}"
  : "${STUB_LOBBY_PORT:=4002}"
  export API_PORT CLIENT_PORT POSTGRES_PORT POSTGRES_HOST POSTGRES_USER \
         POSTGRES_PASSWORD POSTGRES_DB DATABASE_URL STUB_LOBBY_PORT
}

# ---- Fail fast if a port is already in use ----------------------------------
require_free_port() {
  local port="$1" label="$2"
  if lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    err "Port ${port} (${label}) is already in use."
    err "Go Forth! uses ${CLIENT_PORT:-5175}/${API_PORT:-3002}/${POSTGRES_PORT:-5434}; rpslr uses 5174/3001/5433; Lobby uses 5173/8080/5432."
    err "Stop whatever is on :${port}, or change it in .env, then retry."
    exit 1
  fi
}

# ---- docker compose wrapper (supports v1 and v2) ----------------------------
dc() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
  else
    die "docker compose not found. Install Docker Desktop or the compose plugin."
  fi
}

# Resolve a mutable tag to an immutable registry digest so a cluster cannot
# reuse a cached layer from an earlier push of the same tag.
# Set PIN_IMAGE_DIGEST=false to skip (not recommended outside local).
resolve_image_digest() {
  local ref=$1
  if [ "${PIN_IMAGE_DIGEST:-true}" != "true" ]; then
    echo "$ref"; return
  fi
  if [[ "$ref" == *@sha256:* ]]; then
    echo "$ref"; return
  fi
  if ! command -v docker >/dev/null 2>&1; then
    warn "docker not available — cannot pin digest for $ref"
    echo "$ref"; return
  fi
  if ! docker image inspect "$ref" >/dev/null 2>&1; then
    log "Pulling $ref to resolve digest..."
    docker pull "$ref" >/dev/null
  fi
  local digest pinned
  digest=$(docker image inspect "$ref" --format '{{index .RepoDigests 0}}' 2>/dev/null | sed 's/.*@//')
  if [ -z "$digest" ]; then
    warn "Pulling $ref (no local digest yet)..."
    docker pull "$ref" >/dev/null || true
    digest=$(docker image inspect "$ref" --format '{{index .RepoDigests 0}}' 2>/dev/null | sed 's/.*@//')
  fi
  if [ -n "$digest" ]; then
    pinned="${ref%%@*}@${digest}"
    info "Pinned ${ref} → ${pinned}"
    echo "$pinned"
  else
    warn "Could not resolve digest for $ref — the deploy may use a stale cached tag"
    echo "$ref"
  fi
}

pin_deployment_images() {
  local ns=$1 api_ref=$2 client_ref=$3
  log "Setting deployment images (digest-pinned when available)..."
  kubectl -n "$ns" set image deployment/go-forth-api api="$api_ref" migrate="$api_ref"
  kubectl -n "$ns" set image deployment/go-forth-client client="$client_ref"
}

# Refuse mutable :latest — the demo games share registry repos by owner, and a
# :latest push from one has landed in another's cluster before.
assert_safe_image_tag() {
  local tag=$1
  if [ -z "$tag" ]; then
    die "IMAGE_TAG is empty — set an explicit per-game tag (see scripts/game-k8s.defaults.sh)."
  fi
  if [ "$tag" = "latest" ] && [ "${ALLOW_LATEST_TAG:-false}" != "true" ]; then
    die "IMAGE_TAG=:latest is forbidden (cross-game deploy risk). Use DEFAULT_IMAGE_TAG from game-k8s.defaults.sh, or set ALLOW_LATEST_TAG=true to override."
  fi
}

# After a rollout, confirm the deployed API actually answers.
#
# JQ-188 adds /api/v1/status, which names which game is running and is the real
# check — until then /healthz at least proves this namespace serves a live API
# rather than a stale rollout that never became ready.
verify_deployed_health() {
  local ns=$1 public_host=${2:-}

  if [ -n "$public_host" ] && command -v curl >/dev/null 2>&1; then
    if curl -fsS --max-time 20 "https://${public_host}/healthz" >/dev/null 2>&1; then
      ok "https://${public_host}/healthz returned 200"
      return 0
    fi
    warn "https://${public_host}/healthz did not answer — falling back to an in-cluster check."
  fi

  if kubectl exec -n "$ns" deploy/go-forth-api -- \
       python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('API_PORT','3002')+'/healthz')" \
       >/dev/null 2>&1; then
    ok "In-cluster /healthz is green in namespace ${ns}."
    return 0
  fi

  die "Could not get a 200 from /healthz for namespace ${ns} (host=${public_host:-in-cluster})."
}
