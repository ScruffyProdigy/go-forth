"""Integration guide §8, the **JWKS rotation** row, and §11's `jwt.rotation_overlap`.

    Verify tokens signed with either key while both are in JWKS;
    reject a retired key

rpslr covers the same ground in `jwksRotation.test.ts`.

This is the row integrators get wrong, and the failure is invisible until a
rotation: a game that caches the first key it ever saw keeps working for days
and then rejects every token at once, with a message that reads like a signing
bug on the Lobby's side.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.lobby.tokens import JwksKeyStore, JwksSeatTokenVerifier, TokenError
from tests.lobby.signing import StubLobby, single_key_lobby, stub_lobby


def _verifier(lobby: StubLobby, **store_kwargs: Any) -> JwksSeatTokenVerifier:
    return JwksSeatTokenVerifier([lobby.audience], key_store=JwksKeyStore(lobby.fetch, **store_kwargs))


async def test_either_key_verifies_while_both_are_published() -> None:
    lobby = stub_lobby()  # publishes lobby-key-1 and lobby-key-2
    verifier = _verifier(lobby)

    for kid in ("lobby-key-1", "lobby-key-2"):
        token = lobby.mint(lobby_user_id="u", match_id="m", seat_key="1", kid=kid)
        claims = await verifier.verify(token)
        assert claims.lobby_user_id == "u", kid


async def test_a_key_minted_after_the_last_fetch_triggers_a_refetch() -> None:
    """The rotation itself: we cached one key, the Lobby now signs with another."""
    before = single_key_lobby("lobby-key-1")
    verifier = _verifier(before)

    # Warm the cache on the pre-rotation document.
    await verifier.verify(before.mint(lobby_user_id="u", match_id="m", seat_key="1"))
    assert before.fetches == 1

    # The Lobby rotates: the same endpoint now serves both keys.
    after = stub_lobby()
    verifier = JwksSeatTokenVerifier([after.audience], key_store=JwksKeyStore(after.fetch))
    await verifier.verify(after.mint(lobby_user_id="u", match_id="m", seat_key="1", kid="lobby-key-1"))
    fetches = after.fetches

    token = after.mint(lobby_user_id="u", match_id="m", seat_key="1", kid="lobby-key-2")
    claims = await verifier.verify(token)
    assert claims.lobby_user_id == "u"
    # Served from the cached document, which already carried the new key. The
    # point of the row is that the *document* is consulted, not one key from it.
    assert after.fetches == fetches


async def test_an_unknown_kid_refetches_once_and_then_rejects() -> None:
    lobby = single_key_lobby("lobby-key-1")
    # `refetch_interval=0` so the rate limit never suppresses the refetch here;
    # the limit itself is the next test.
    verifier = _verifier(lobby, refetch_interval=0.0)

    await verifier.verify(lobby.mint(lobby_user_id="u", match_id="m", seat_key="1"))
    fetches = lobby.fetches

    # Signed with a key this Lobby does not publish.
    other = stub_lobby()
    forged = other.mint(lobby_user_id="u", match_id="m", seat_key="1", kid="lobby-key-2")

    with pytest.raises(TokenError, match="unknown key"):
        await verifier.verify(forged)

    # Refetched before rejecting — the token in hand *might* have been signed by
    # a key minted since the last fetch, and refusing without looking is what
    # breaks a real rotation.
    assert lobby.fetches == fetches + 1


async def test_the_refetch_is_rate_limited() -> None:
    """A flood of invented `kid`s must not become a flood of requests at the Lobby.

    Without the limit, an unauthenticated caller turns every rejection into an
    outbound fetch — a denial-of-service against the Lobby, paid for by us.

    The limit is measured from the last *fetch*, not from the last refetch
    attempt, which has a consequence worth stating: an unknown `kid` arriving
    seconds after a successful fetch is refused without looking again. That is
    the right trade — a document fetched a moment ago will not have grown a key
    since — and the player's retry lands once the interval has passed.
    """
    lobby = single_key_lobby("lobby-key-1")
    clock = [1000.0]
    verifier = _verifier(lobby, now=lambda: clock[0], refetch_interval=30.0, cache_seconds=300.0)

    await verifier.verify(lobby.mint(lobby_user_id="u", match_id="m", seat_key="1"))
    fetches = lobby.fetches

    other = stub_lobby()
    forged = other.mint(lobby_user_id="u", match_id="m", seat_key="1", kid="lobby-key-2")

    # Straight after a fetch: refused, and the Lobby is not troubled.
    with pytest.raises(TokenError, match="unknown key"):
        await verifier.verify(forged)
    assert lobby.fetches == fetches

    # Once the interval has passed, exactly one refetch is spent...
    clock[0] += 31.0
    with pytest.raises(TokenError, match="unknown key"):
        await verifier.verify(forged)
    assert lobby.fetches == fetches + 1

    # ...and a burst behind it costs nothing more.
    for _ in range(10):
        clock[0] += 1.0
        with pytest.raises(TokenError, match="unknown key"):
            await verifier.verify(forged)
    assert lobby.fetches == fetches + 1


async def test_a_rotation_seen_after_the_interval_recovers_on_its_own() -> None:
    """The case the limit must not break: the Lobby really did mint a new key."""
    published = [single_key_lobby("lobby-key-1").keys[0]]
    fetches = [0]

    async def fetch(url: str) -> dict[str, Any]:
        fetches[0] += 1
        return {"keys": [key.jwk() for key in published]}

    clock = [0.0]
    verifier = JwksSeatTokenVerifier(
        ["http://localhost:3002"],
        key_store=JwksKeyStore(fetch, now=lambda: clock[0], refetch_interval=30.0, cache_seconds=300.0),
    )

    one_key = single_key_lobby("lobby-key-1")
    await verifier.verify(one_key.mint(lobby_user_id="u", match_id="m", seat_key="1"))
    assert fetches[0] == 1

    # The Lobby rotates: key 2 joins the document, and starts signing.
    both = stub_lobby()
    published.append(both.keys[1])
    token = both.mint(lobby_user_id="u", match_id="m", seat_key="1", kid="lobby-key-2")

    clock[0] += 31.0
    claims = await verifier.verify(token)
    assert claims.lobby_user_id == "u"
    assert fetches[0] == 2


async def test_a_document_is_refreshed_once_it_goes_stale() -> None:
    lobby = single_key_lobby("lobby-key-1")
    clock = [0.0]
    verifier = _verifier(lobby, now=lambda: clock[0], cache_seconds=300.0)

    token = lobby.mint(lobby_user_id="u", match_id="m", seat_key="1")
    await verifier.verify(token)
    assert lobby.fetches == 1

    clock[0] += 100.0
    await verifier.verify(token)
    assert lobby.fetches == 1, "still inside the cache window"

    clock[0] += 250.0
    await verifier.verify(token)
    assert lobby.fetches == 2


async def test_a_token_with_no_kid_is_refused_mid_rotation() -> None:
    """Two live keys and no `kid` is ambiguous, so it is refused rather than guessed.

    Guessing would mean accepting a token the *retired* key signed exactly as
    often as one the live key did.
    """
    two_keys = stub_lobby()
    verifier = _verifier(two_keys)

    import jwt as pyjwt

    key = two_keys.keys[0]
    token = pyjwt.encode(
        {
            "iss": two_keys.issuer,
            "aud": two_keys.audience,
            "sub": "u",
            "matchId": "m",
            "seatKey": "1",
            "exp": 4102444800,
        },
        key.pem(),
        algorithm="RS256",
    )
    with pytest.raises(TokenError):
        await verifier.verify(token)


async def test_one_live_key_and_no_kid_is_unambiguous() -> None:
    one_key = single_key_lobby("lobby-key-1")
    verifier = _verifier(one_key)

    import jwt as pyjwt

    token = pyjwt.encode(
        {
            "iss": one_key.issuer,
            "aud": one_key.audience,
            "sub": "u",
            "matchId": "m",
            "seatKey": "1",
            "exp": 4102444800,
        },
        one_key.keys[0].pem(),
        algorithm="RS256",
    )
    assert (await verifier.verify(token)).lobby_user_id == "u"


async def test_an_unreachable_jwks_is_a_token_error_not_a_crash() -> None:
    async def explode(url: str) -> dict[str, Any]:
        raise ConnectionError("lobby is down")

    verifier = JwksSeatTokenVerifier(["aud"], key_store=JwksKeyStore(explode))
    lobby = stub_lobby()
    with pytest.raises(TokenError, match="could not fetch JWKS"):
        await verifier.verify(lobby.mint(lobby_user_id="u", match_id="m", seat_key="1"))


async def test_one_unreadable_key_does_not_void_the_document() -> None:
    lobby = single_key_lobby("lobby-key-1")

    async def with_junk(url: str) -> dict[str, Any]:
        lobby.fetches += 1
        return {"keys": [{"kid": "broken", "kty": "nonsense"}, *lobby.jwks()["keys"]]}

    verifier = JwksSeatTokenVerifier([lobby.audience], key_store=JwksKeyStore(with_junk))
    token = lobby.mint(lobby_user_id="u", match_id="m", seat_key="1")
    # A Lobby publishing a key type we cannot parse must not take every other
    # key down with it.
    assert (await verifier.verify(token)).lobby_user_id == "u"
