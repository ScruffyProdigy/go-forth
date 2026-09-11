#!/usr/bin/env bash
# Deploy to a LOCAL cluster (kind / minikube / docker-desktop).
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
exec "$REPO_ROOT/scripts/_deploy.sh" local
