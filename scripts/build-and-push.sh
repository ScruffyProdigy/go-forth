#!/usr/bin/env bash
# Build (and optionally push) the Go Forth! Docker images.
#
# Defaults match the k8s/base manifests (Docker Hub). Override for GHCR:
#   REGISTRY=ghcr.io IMAGE_OWNER=joinquest ./scripts/build-and-push.sh --push
#
#   ./scripts/build-and-push.sh           # build only
#   ./scripts/build-and-push.sh --push    # build + push (needs a registry login)
#
# Both images build from the REPO ROOT as their context, so the root
# .dockerignore is the single authority on what reaches the daemon — including
# keeping sibling agent worktrees under .claude/ out of it.

set -euo pipefail

PUSH=false
for arg in "$@"; do
  case "$arg" in
    --push) PUSH=true ;;
    -h|--help) echo "Usage: $0 [--push]"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 1 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
# shellcheck disable=SC1091
source "$REPO_ROOT/scripts/game-k8s.defaults.sh"

REGISTRY="${REGISTRY:-docker.io}"
IMAGE_OWNER="${IMAGE_OWNER:-scruffyprodigy}"
API_IMAGE="${REGISTRY}/${IMAGE_OWNER}/${API_IMAGE_NAME}"
CLIENT_IMAGE="${REGISTRY}/${IMAGE_OWNER}/${CLIENT_IMAGE_NAME}"
TAG="${TAG:-$DEFAULT_IMAGE_TAG}"

if [ "$TAG" = "latest" ] && [ "${ALLOW_LATEST_TAG:-false}" != "true" ]; then
  echo "Refusing to build :latest — use TAG=${DEFAULT_IMAGE_TAG} (or ALLOW_LATEST_TAG=true)." >&2
  exit 1
fi

# The build context is the working tree, so an uncommitted edit — including one
# another agent left in this checkout — would ship in the image with nothing in
# git recording it. Refuse by default.
command -v git >/dev/null 2>&1 || { echo "git not found — cannot verify the tree is clean." >&2; exit 1; }
git rev-parse --git-dir >/dev/null 2>&1 || { echo "${REPO_ROOT} is not a git checkout — refusing to build." >&2; exit 1; }

DIRTY="$(git status --porcelain)"
if [ -n "$DIRTY" ]; then
  if [ "${ALLOW_DIRTY_TREE:-false}" != "true" ]; then
    echo "Refusing to build from a dirty tree — the image would ship uncommitted work." >&2
    echo "Uncommitted paths in ${REPO_ROOT}:" >&2
    printf '%s\n' "$DIRTY" | sed 's/^/  /' >&2
    echo "Commit them, or re-run with ALLOW_DIRTY_TREE=true." >&2
    exit 1
  fi
  echo "Warning: ALLOW_DIRTY_TREE=true — building from a dirty tree." >&2
fi

GIT_SHA="$(git rev-parse HEAD)"

# org.opencontainers.image.revision is meant to be resolvable as-is, so
# dirtiness rides on its own label rather than as a "-dirty" suffix on a SHA
# that no lookup would then find.
LABEL_ARGS=(--label "org.opencontainers.image.revision=${GIT_SHA}")
DIRTY_NOTE=""
if [ -n "$DIRTY" ]; then
  LABEL_ARGS+=(--label "com.joinquest.image.dirty-tree=true")
  DIRTY_NOTE=" (dirty tree)"
fi

# A commit only this machine has is not traceable by anyone else. Warn rather
# than refuse — building before pushing is legitimate.
if [ -z "$(git branch -r --contains HEAD 2>/dev/null)" ]; then
  echo "Warning: ${GIT_SHA} is on no remote — push it, or nobody else can resolve what shipped." >&2
fi

command -v docker >/dev/null 2>&1 || { echo "docker not found" >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker is not running" >&2; exit 1; }

docker_config_json() { echo "${DOCKER_CONFIG:-$HOME/.docker}/config.json"; }

if [ "$PUSH" = true ]; then
  case "$REGISTRY" in
    ghcr.io)
      grep -q 'ghcr.io' "$(docker_config_json)" 2>/dev/null \
        || { echo "GHCR login not found in $(docker_config_json). Run: docker login ghcr.io" >&2; exit 1; }
      ;;
    docker.io)
      grep -q 'index.docker.io' "$(docker_config_json)" 2>/dev/null \
        || { echo "Docker Hub login not found in $(docker_config_json). Run: docker login" >&2; exit 1; }
      ;;
  esac
fi

echo "Building from commit ${GIT_SHA}${DIRTY_NOTE}"

echo "Building API image..."
docker build "${LABEL_ARGS[@]}" -t "${API_IMAGE}:${TAG}" -f api/Dockerfile .

echo "Building client image..."
docker build "${LABEL_ARGS[@]}" -t "${CLIENT_IMAGE}:${TAG}" -f client/Dockerfile .

if [ "$PUSH" = true ]; then
  echo "Pushing images..."
  docker push "${API_IMAGE}:${TAG}"
  docker push "${CLIENT_IMAGE}:${TAG}"
else
  echo "Built locally. To push: $0 --push"
fi

echo "API:    ${API_IMAGE}:${TAG}"
echo "Client: ${CLIENT_IMAGE}:${TAG}"
echo "Commit: ${GIT_SHA}${DIRTY_NOTE}"
