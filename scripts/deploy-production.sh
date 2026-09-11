#!/usr/bin/env bash
# Deploy to PRODUCTION. Prompts for confirmation.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

warn "You are about to deploy Go Forth! to PRODUCTION."
warn "Cluster context: $(kubectl config current-context 2>/dev/null || echo 'unknown')"
read -r -p "Type 'production' to continue: " confirm
[ "$confirm" = "production" ] || die "Aborted."

exec "$REPO_ROOT/scripts/_deploy.sh" production
