#!/usr/bin/env bash
# One-time setup: copy .env, install api + client dependencies.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

log "Setting up Go Forth!..."

if [ ! -f "$REPO_ROOT/.env" ]; then
  cp "$REPO_ROOT/.env.example" "$REPO_ROOT/.env"
  ok "Created .env from .env.example"
else
  info ".env already exists — leaving it untouched"
fi

# The api is Python, the client is Node. Check both up front rather than
# failing halfway through an install.
node_major="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
if [ "$node_major" -lt 20 ]; then
  warn "Node ${node_major} detected. The client targets Node 20 LTS."
fi

# Find an interpreter that satisfies api/pyproject.toml's >=3.12. Named
# versions first: `python3` is 3.9 on a stock macOS, which would build a venv
# that cannot install the dependencies and fail confusingly later.
PYTHON=""
for candidate in python3.13 python3.12 python3; do
  if command -v "$candidate" >/dev/null 2>&1 \
    && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
    PYTHON="$candidate"
    break
  fi
done
if [ -z "$PYTHON" ]; then
  err "No Python 3.12+ found. The api needs it (see api/pyproject.toml)."
  err "macOS:  brew install python@3.12"
  err "Or run the suite in a container instead:"
  err "  docker run --rm -v \"\$PWD/api:/app\" -w /app python:3.12-slim bash -c 'pip install -e \".[dev]\" && pytest'"
  exit 1
fi
info "Using $("$PYTHON" --version) for the api"

log "Installing API dependencies..."
if [ ! -d "$REPO_ROOT/api/.venv" ]; then
  "$PYTHON" -m venv "$REPO_ROOT/api/.venv"
  ok "Created api/.venv"
fi
# uv is faster and reads the same pyproject.toml, but nothing requires it.
if command -v uv >/dev/null 2>&1; then
  (cd "$REPO_ROOT/api" && VIRTUAL_ENV="$REPO_ROOT/api/.venv" uv pip install -e ".[dev]")
else
  (cd "$REPO_ROOT/api" && ./.venv/bin/pip install --quiet --upgrade pip && ./.venv/bin/pip install -e ".[dev]")
fi
ok "API deps installed"

log "Installing client dependencies..."
(cd "$REPO_ROOT/client" && npm install)
ok "Client deps installed"

ok "Setup complete. Next: ${C_BOLD}./scripts/dev.sh${C_RESET}"
