"""Seat tokens: what the Lobby signs, and what this game will accept.

A seat JWT binds one Lobby user to one seat of one match. Lobby owns
matchmaking; it pushes the match server-to-server first (`provision.py`) and
*then* links each player with a token proving who they are, so a token can only
open the seat already reserved for its `sub`. The token never carries the
roster — the pushed match is the source of truth.

Claims:

    iss      Lobby issuer URL — the same value provision sent as `lobbyId`
    aud      this game's API origin
    sub      Lobby user id
    matchId  the Lobby match id, which is our `externalMatchId`
    seatKey  the seat reserved for this user
    name     display name (optional)
    exp/nbf/iat/jti  standard time and uniqueness claims

## Why the JWKS cache is written out rather than taken from PyJWT

`PyJWKClient` would do most of this. It is spelled out here because **key
rotation is the part integrators get wrong**, and a reference implementation
whose rotation behaviour lives inside a library dependency teaches nobody what
the rule is. The rule (integration guide §6): Lobby's JWKS may carry more than
one active key during a rotation; match the token's `kid` header against the
document, and on an unrecognised `kid` **refetch before rejecting** — because
the token in your hand may be signed with a key minted since your last fetch.

The refetch is rate-limited. Without that, an attacker with a stream of tokens
carrying invented `kid`s turns every rejection into an outbound request to the
Lobby, which is a denial-of-service against the Lobby paid for by this game.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import jwt
from jwt import PyJWK

from app.lobby.issuer import lobby_jwks_url, normalize_lobby_issuer

#: Seconds between JWKS fetches for one issuer when the `kid` is unrecognised.
#: Long enough that a flood of invented `kid`s cannot be aimed at the Lobby,
#: short enough that a genuine rotation is picked up within one player's retry.
JWKS_REFETCH_INTERVAL_SECONDS = 30.0

#: How long a fetched document is served before it is refreshed on its own.
JWKS_CACHE_SECONDS = 300.0


class TokenError(Exception):
    """A seat token this game will not accept. Always a 401 at the edge."""


@dataclass(frozen=True, slots=True)
class AssignmentClaims:
    """The verified content of a seat token."""

    #: JWT `iss`, normalised — must match the match's provisioned `lobbyId`.
    lobby_issuer: str
    lobby_user_id: str
    external_match_id: str
    seat_key: str
    display_name: str | None = None


def claims_from_payload(payload: Mapping[str, Any]) -> AssignmentClaims:
    """Read the game-specific claims off a payload whose signature already checked out.

    Both spellings of the two custom claims are accepted, because the two sides
    of this contract were written months apart and a token that verifies but is
    then rejected for `match_id` vs `matchId` is the least debuggable failure
    this path has.
    """
    issuer = payload.get("iss")
    if not isinstance(issuer, str) or not issuer.strip():
        raise TokenError("token missing iss")

    subject = payload.get("sub")
    match_id = payload.get("matchId") or payload.get("match_id")
    seat_key = payload.get("seatKey") or payload.get("seat_key")

    if not isinstance(subject, str) or not subject.strip():
        raise TokenError("token missing sub")
    if not isinstance(match_id, str) or not match_id.strip():
        raise TokenError("token missing matchId")
    if not isinstance(seat_key, str) or not seat_key.strip():
        raise TokenError("token missing seatKey")

    name = payload.get("name") or payload.get("displayName")
    return AssignmentClaims(
        lobby_issuer=normalize_lobby_issuer(issuer),
        lobby_user_id=subject.strip(),
        external_match_id=match_id.strip(),
        seat_key=seat_key.strip(),
        display_name=name.strip() if isinstance(name, str) and name.strip() else None,
    )


class SeatTokenVerifier(Protocol):
    """Pluggable so tests inject a signer instead of standing up a Lobby."""

    async def verify(self, token: str) -> AssignmentClaims: ...


#: Fetches one JWKS document. Injected so tests never open a socket.
JwksFetcher = Callable[[str], Awaitable[Mapping[str, Any]]]


async def _fetch_jwks_over_https(url: str) -> Mapping[str, Any]:
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        body = response.json()
    if not isinstance(body, dict):
        raise TokenError(f"JWKS at {url} is not a JSON object")
    return body


@dataclass
class _CachedJwks:
    keys: dict[str, PyJWK]
    fetched_at: float


class JwksKeyStore:
    """Signing keys per issuer, refetched on an unrecognised `kid`."""

    def __init__(
        self,
        fetch: JwksFetcher | None = None,
        *,
        now: Callable[[], float] = time.monotonic,
        refetch_interval: float = JWKS_REFETCH_INTERVAL_SECONDS,
        cache_seconds: float = JWKS_CACHE_SECONDS,
    ) -> None:
        self._fetch = fetch or _fetch_jwks_over_https
        self._now = now
        self._refetch_interval = refetch_interval
        self._cache_seconds = cache_seconds
        self._cache: dict[str, _CachedJwks] = {}

    async def signing_key(self, issuer: str, kid: str | None) -> PyJWK:
        url = lobby_jwks_url(issuer)
        cached = self._cache.get(url)

        stale = cached is None or (self._now() - cached.fetched_at) >= self._cache_seconds
        if stale:
            cached = await self._refresh(url)

        assert cached is not None  # `_refresh` either populates or raises
        key = self._select(cached, kid)
        if key is not None:
            return key

        # The unrecognised-`kid` refetch. A token signed with a key minted since
        # the last fetch is legitimate, and is the whole reason this branch
        # exists — but it is also exactly what a flood of invented `kid`s looks
        # like, so it is rate-limited rather than run per rejection.
        if (self._now() - cached.fetched_at) < self._refetch_interval:
            raise TokenError("token signed with an unknown key")

        refreshed = await self._refresh(url)
        key = self._select(refreshed, kid)
        if key is None:
            raise TokenError("token signed with an unknown key")
        return key

    def _select(self, cached: _CachedJwks, kid: str | None) -> PyJWK | None:
        if kid is not None:
            return cached.keys.get(kid)
        # A JWKS with exactly one key is unambiguous without a `kid`. With two,
        # picking one would mean accepting a token a retired key signed as often
        # as one the live key did — so a token with no `kid` is refused mid-
        # rotation rather than guessed at.
        if len(cached.keys) == 1:
            return next(iter(cached.keys.values()))
        return None

    async def _refresh(self, url: str) -> _CachedJwks:
        try:
            document = await self._fetch(url)
        except TokenError:
            raise
        except Exception as err:
            raise TokenError(f"could not fetch JWKS from {url}") from err

        raw_keys = document.get("keys")
        if not isinstance(raw_keys, list) or not raw_keys:
            raise TokenError(f"JWKS at {url} carries no keys")

        keys: dict[str, PyJWK] = {}
        for entry in raw_keys:
            if not isinstance(entry, dict):
                continue
            kid = entry.get("kid")
            if not isinstance(kid, str) or not kid:
                continue
            try:
                keys[kid] = PyJWK.from_dict(entry)
            except Exception:
                continue

        if not keys:
            raise TokenError(f"JWKS at {url} carries no usable keys")

        cached = _CachedJwks(keys=keys, fetched_at=self._now())
        self._cache[url] = cached
        return cached


class JwksSeatTokenVerifier:
    """Verifies seat tokens against the JWKS of the issuer each token names.

    The issuer is read from the *unverified* token only to decide which JWKS to
    consult; it is then enforced as a verified claim, so a token cannot name one
    issuer in its header path and another in its signed body.
    """

    def __init__(
        self,
        audiences: Sequence[str] = (),
        *,
        key_store: JwksKeyStore | None = None,
    ) -> None:
        self._audiences = tuple(a for a in audiences if a)
        self._keys = key_store or JwksKeyStore()

    async def verify(self, token: str) -> AssignmentClaims:
        try:
            header = jwt.get_unverified_header(token)
            unverified = jwt.decode(token, options={"verify_signature": False})
        except jwt.PyJWTError as err:
            raise TokenError("invalid lobby token") from err

        issuer = unverified.get("iss")
        if not isinstance(issuer, str) or not issuer.strip():
            raise TokenError("token missing iss")
        issuer = issuer.strip()

        kid = header.get("kid")
        key = await self._keys.signing_key(issuer, kid if isinstance(kid, str) else None)

        try:
            payload = jwt.decode(
                token,
                key,
                algorithms=["RS256", "ES256"],
                issuer=issuer,
                audience=list(self._audiences) if self._audiences else None,
                options={
                    "require": ["iss", "sub", "exp"],
                    "verify_aud": bool(self._audiences),
                },
            )
        except jwt.PyJWTError as err:
            # One message for every failure mode on purpose. "expired" versus
            # "wrong audience" is a probe an unauthenticated caller should not
            # be handed; the server log carries the detail.
            raise TokenError("invalid lobby token") from err

        return claims_from_payload(payload)


def create_seat_token_verifier(audiences: Sequence[str] = ()) -> SeatTokenVerifier:
    return JwksSeatTokenVerifier(audiences)
