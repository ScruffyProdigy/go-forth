#!/usr/bin/env bash
# Non-interactive production deploy, for CI or a scripted release. Prefer
# deploy-production.sh by hand — this one does not ask.
set -euo pipefail
exec "$(dirname "${BASH_SOURCE[0]}")/_deploy.sh" production
