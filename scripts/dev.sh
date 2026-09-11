#!/usr/bin/env bash
# Start the full local dev stack: Postgres + migrate + API (:3002) + Vite (:5175).
# Traps SIGINT so Ctrl+C takes the children down with it.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
load_env

CHILD_PIDS=()

cleanup() {
  echo
  log "Shutting down dev stack..."
  for pid in "${CHILD_PIDS[@]:-}"; do
    if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  ok "Stopped API + client. (Postgres left running — './scripts/db.sh down' to stop it.)"
  exit 0
}
trap cleanup INT TERM

# 1. Pre-flight port checks, so a collision with rpslr or the Lobby is a clear
#    error rather than a half-started stack.
require_free_port "$API_PORT" "go-forth API"
require_free_port "$CLIENT_PORT" "go-forth client"

# 2. Postgres + migrations.
"$REPO_ROOT/scripts/db.sh" up
"$REPO_ROOT/scripts/db.sh" migrate

# 3. API (background). Through the venv's interpreter rather than `python`, so
#    dev.sh works without the venv being activated in the calling shell.
log "Starting API on :${API_PORT}..."
[ -x "$REPO_ROOT/api/.venv/bin/python" ] || die "api/.venv is missing — run ./scripts/setup.sh first."
(cd "$REPO_ROOT/api" && ./.venv/bin/python -m app.server) &
CHILD_PIDS+=($!)

# 4. Client (background).
log "Starting client (Vite) on :${CLIENT_PORT}..."
(cd "$REPO_ROOT/client" && npm run dev) &
CHILD_PIDS+=($!)

sleep 2
echo
ok "Dev stack is up:"
printf "   ${C_BOLD}Game UI${C_RESET}     %s\n" "http://localhost:${CLIENT_PORT}"
printf "   ${C_BOLD}Game API${C_RESET}    %s\n" "http://localhost:${API_PORT}  (try /healthz)"
printf "   ${C_BOLD}Postgres${C_RESET}    %s\n" "localhost:${POSTGRES_PORT} (db=${POSTGRES_DB})"
echo
info "No lobby? ./scripts/stub-lobby.sh serve  — local JWKS + provisioning stub."
info "Press Ctrl+C to stop the API and client."

# Keep the script alive while the children run.
wait
