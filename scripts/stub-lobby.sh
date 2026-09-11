#!/usr/bin/env bash
# Stand in for the JoinQuest Lobby so Go Forth! runs standalone — the v1 mode
# rpslr shipped with, where the game is playable with no platform in front of it.
#
#   ./scripts/stub-lobby.sh serve       run the stub Lobby (JWKS + token endpoint)
#   ./scripts/stub-lobby.sh jwks        print the JWKS document
#   ./scripts/stub-lobby.sh token [user] [match] [seat]
#                                       mint one seat JWT and print it
#   ./scripts/stub-lobby.sh provision   push a match assignment at the game API
#
# The JWKS and token halves work today. `provision` calls POST /api/v1/matches,
# which JQ-188 builds — until then it reports the 404 and prints the payload it
# would have sent, so the wire shape is still reviewable.
#
# The signing key is generated on first use and cached in .stub-lobby/
# (gitignored) so tokens keep verifying across restarts.
#
# Python rather than Node, though the client's toolchain is Node: what this
# demonstrates is §8's JWT-claim and JWKS-rotation rows, and a developer reading
# the Python reference should not have to read JavaScript to follow the auth stub.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
load_env

[ -x "$REPO_ROOT/api/.venv/bin/python" ] || die "api/.venv is missing — run ./scripts/setup.sh first."

cmd="${1:-}"
case "$cmd" in
  serve|jwks|token|provision)
    exec "$REPO_ROOT/api/.venv/bin/python" "$REPO_ROOT/scripts/stub_lobby.py" "$@"
    ;;
  *)
    err "Unknown command: '${cmd}'"
    echo "Usage: $0 {serve|jwks|token [user] [match] [seat]|provision}"
    exit 1
    ;;
esac
