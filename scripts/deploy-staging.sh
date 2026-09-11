#!/usr/bin/env bash
# Deploy to STAGING.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
exec "$REPO_ROOT/scripts/_deploy.sh" staging
