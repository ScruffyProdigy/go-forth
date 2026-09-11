#!/usr/bin/env bash
# Run all tests (api + client) from the repo root, in subshells so the caller's
# working directory is never left changed.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

failed=0

log "Running API tests..."
# Everything CI runs, in CI's order, so a green run here means a green run there.
if (cd "$REPO_ROOT/api" \
      && ./.venv/bin/ruff check . \
      && ./.venv/bin/ruff format --check . \
      && ./.venv/bin/mypy app tests \
      && ./.venv/bin/pytest); then
  ok "API tests passed"
else
  err "API tests failed"
  failed=1
fi

echo
log "Running client tests..."
if (cd "$REPO_ROOT/client" && npm test); then
  ok "Client tests passed"
else
  err "Client tests failed"
  failed=1
fi

echo
if [ "$failed" -eq 0 ]; then
  ok "All tests passed."
else
  die "Some tests failed."
fi
