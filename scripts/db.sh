#!/usr/bin/env bash
# Manage Go Forth!'s own Postgres (host port 5434).
#   ./scripts/db.sh up        start postgres (docker compose)
#   ./scripts/db.sh down      stop postgres
#   ./scripts/db.sh migrate   run SQL migrations
#   ./scripts/db.sh reset     drop the volume, recreate, migrate
#   ./scripts/db.sh psql      open a psql shell in the container
#   ./scripts/db.sh url       print the DATABASE_URL
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
load_env

wait_for_pg() {
  log "Waiting for Postgres on :${POSTGRES_PORT}..."
  for _ in $(seq 1 30); do
    if (cd "$REPO_ROOT" && dc exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB") >/dev/null 2>&1; then
      ok "Postgres is ready."
      return 0
    fi
    sleep 1
  done
  die "Postgres did not become ready in time."
}

cmd="${1:-}"
case "$cmd" in
  up)
    # Idempotent: if our own container is already up and healthy, reuse it
    # rather than tripping the port check on ourselves.
    if [ -n "$(cd "$REPO_ROOT" && dc ps -q postgres 2>/dev/null)" ] \
      && (cd "$REPO_ROOT" && dc exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB") >/dev/null 2>&1; then
      ok "Go Forth! Postgres already running (host port ${POSTGRES_PORT})."
    else
      require_free_port "$POSTGRES_PORT" "go-forth postgres"
      log "Starting Postgres (host port ${POSTGRES_PORT})..."
      (cd "$REPO_ROOT" && dc up -d postgres)
      wait_for_pg
    fi
    ;;
  down)
    log "Stopping Postgres..."
    (cd "$REPO_ROOT" && dc down)
    ok "Stopped."
    ;;
  migrate)
    log "Running migrations against ${DATABASE_URL}..."
    [ -x "$REPO_ROOT/api/.venv/bin/python" ] || die "api/.venv is missing — run ./scripts/setup.sh first."
    (cd "$REPO_ROOT/api" && ./.venv/bin/python -m app.migrate)
    ok "Migrations complete."
    ;;
  reset)
    warn "Destroying the database volume and recreating..."
    (cd "$REPO_ROOT" && dc down -v)
    (cd "$REPO_ROOT" && dc up -d postgres)
    wait_for_pg
    (cd "$REPO_ROOT/api" && ./.venv/bin/python -m app.migrate)
    ok "Database reset and migrated."
    ;;
  psql)
    (cd "$REPO_ROOT" && dc exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB")
    ;;
  url)
    echo "$DATABASE_URL"
    ;;
  *)
    err "Unknown command: '${cmd}'"
    echo "Usage: $0 {up|down|migrate|reset|psql|url}"
    exit 1
    ;;
esac
