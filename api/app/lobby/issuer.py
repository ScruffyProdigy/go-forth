"""Normalising a Lobby issuer URL, and the two endpoints derived from it.

The game stores no per-environment Lobby URL. A seat token names its own issuer
in `iss`, provision names the same value in `lobbyId`, and both the JWKS
document and the GraphQL endpoint hang off it. That is what lets one image serve
local, staging and production without a Lobby address compiled into it.

Normalisation exists because the two sides will spell the same issuer
differently — a trailing slash from a config file, a query string from a copied
link — and a mismatch there rejects every token with a message that reads like a
signing problem. This mirrors Lobby's own `LobbyIssuer()`.
"""

from __future__ import annotations

from urllib.parse import urlsplit


def normalize_lobby_issuer(raw: str) -> str:
    """Strip query, fragment and trailing slash, keeping scheme, host and path.

    Anything that will not parse as a URL is returned trimmed rather than
    raising: this is used to *compare* two issuers, and a caller comparing
    nonsense should get a clean "these differ" instead of an exception.
    """
    trimmed = raw.strip()
    if not trimmed:
        return ""

    parts = urlsplit(trimmed)
    if not parts.scheme or not parts.netloc:
        return trimmed.rstrip("/")

    path = parts.path.rstrip("/")
    return f"{parts.scheme}://{parts.netloc}{path}"


def lobby_jwks_url(lobby_issuer: str) -> str:
    """Where this Lobby publishes its signing keys."""
    return f"{normalize_lobby_issuer(lobby_issuer)}/.well-known/jwks.json"


def lobby_graphql_url(lobby_issuer: str) -> str:
    """Lobby's GraphQL endpoint — the same origin as the issuer."""
    return normalize_lobby_issuer(lobby_issuer)


def lobby_issuers_match(a: str, b: str) -> bool:
    """Whether two spellings name the same Lobby."""
    return normalize_lobby_issuer(a) == normalize_lobby_issuer(b)
