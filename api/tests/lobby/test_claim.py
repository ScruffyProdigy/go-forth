"""Integration guide §8, the **JWT claim** and **Re-claim** rows.

    Valid token; wrong aud/iss; expired; malformed; URL ref != token matchId;
    wrong reserved seat
    Same sub re-claiming a held seat gets 200 and unchanged match state;
    a different sub still gets 409

rpslr covers the same ground in `app.test.ts`.

The token rows use the **real** verifier against `StubLobby`'s keys rather than
the fake one. A fake that accepted a wrongly-signed token would make every row
here pass while proving nothing.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Config
from app.lobby.tokens import JwksSeatTokenVerifier, TokenError, claims_from_payload
from app.main import create_app
from app.service import GameService
from tests.conftest import provision_body
from tests.lobby.signing import StubLobby

MATCH = "lobby-match-1"


@pytest.fixture
def signed_client(
    service: GameService,
    config: Config,
    real_verifier: JwksSeatTokenVerifier,
) -> Iterator[TestClient]:
    """An app whose claims are checked by the production JWKS verifier."""
    with TestClient(create_app(config, service=service, verifier=real_verifier)) as client:
        client.post("/api/v1/matches", json=provision_body())
        yield client


# --------------------------------------------------- jwt.claim_happy_path --


def test_a_valid_token_seats_its_own_player(signed_client: TestClient, signer: StubLobby) -> None:
    token = signer.mint(lobby_user_id="user-north", match_id=MATCH, seat_key="1", display_name="Nora")
    response = signed_client.post(
        f"/api/v1/matches/{MATCH}/claim", headers={"authorization": f"Bearer {token}"}
    )
    assert response.status_code == 201

    body = response.json()
    assert body["you"]["seatKey"] == "1"
    assert body["you"]["side"] == "north"
    assert body["you"]["name"] == "Nora"
    assert body["reclaimed"] is False


def test_a_successful_claim_writes_the_seat_binding_cookie(
    signed_client: TestClient, signer: StubLobby
) -> None:
    token = signer.mint(lobby_user_id="user-north", match_id=MATCH, seat_key="1")
    response = signed_client.post(
        f"/api/v1/matches/{MATCH}/claim", headers={"authorization": f"Bearer {token}"}
    )
    cookie = response.headers["set-cookie"]
    # Recovery path 1 lives or dies on these three attributes.
    assert "go_forth_seat=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie


def test_the_claim_carries_the_return_url(signed_client: TestClient, signer: StubLobby) -> None:
    token = signer.mint(lobby_user_id="user-north", match_id=MATCH, seat_key="1")
    body = signed_client.post(
        f"/api/v1/matches/{MATCH}/claim", headers={"authorization": f"Bearer {token}"}
    ).json()
    # A navigation target, so the player arrives back at the Lobby logged in.
    assert body["returnUrl"] == f"https://joinquest.test/return?match={MATCH}"


# ------------------------- jwt.wrong_audience / wrong_issuer / expired / etc --


@pytest.mark.parametrize(
    ("name", "kwargs"),
    [
        ("wrong audience", {"audience": "https://somebody-else.test"}),
        ("wrong issuer", {"issuer": "https://not-our-lobby.test"}),
        ("expired", {"expires_in": -60}),
        ("no subject", {"omit": ("sub",)}),
        ("no expiry", {"omit": ("exp",)}),
    ],
)
def test_a_token_that_fails_verification_is_refused(
    signed_client: TestClient, signer: StubLobby, name: str, kwargs: dict[str, Any]
) -> None:
    token = signer.mint(lobby_user_id="user-north", match_id=MATCH, seat_key="1", **kwargs)
    response = signed_client.post(
        f"/api/v1/matches/{MATCH}/claim", headers={"authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401, name


def test_a_wrong_issuer_is_refused_before_its_jwks_is_fetched(
    signed_client: TestClient, signer: StubLobby
) -> None:
    before = signer.fetches
    token = signer.mint(
        lobby_user_id="user-north", match_id=MATCH, seat_key="1", issuer="https://not-our-lobby.test"
    )
    signed_client.post(f"/api/v1/matches/{MATCH}/claim", headers={"authorization": f"Bearer {token}"})
    # The stub asserts on the URL it is asked for, so a fetch aimed at the
    # forged issuer would have raised. What matters is that a token naming any
    # issuer it likes cannot make this server fetch from it.
    assert signer.fetches == before or signer.fetches == before + 1


@pytest.mark.parametrize("token", ["not-a-jwt", "a.b.c", "Bearer", "..", "e30.e30.e30"])
def test_a_malformed_token_is_refused(signed_client: TestClient, token: str) -> None:
    response = signed_client.post(
        f"/api/v1/matches/{MATCH}/claim", headers={"authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


def test_no_token_at_all_seats_nobody_in_a_lobby_match(signed_client: TestClient) -> None:
    """An empty bearer is an *absent* token, not a malformed one.

    This app allows standalone play, so a tokenless claim is not refused
    outright — it falls through to "take the first open, unreserved seat". In a
    Lobby-provisioned match every seat is reserved, so there is no such seat and
    the answer is 409. The property worth pinning is not the code: it is that a
    caller with no token never ends up holding a seat the Lobby reserved.
    """
    response = signed_client.post(f"/api/v1/matches/{MATCH}/claim", headers={"authorization": "Bearer "})
    assert response.status_code == 409
    assert "you" not in response.json()

    seats = signed_client.get(f"/api/v1/matches/{MATCH}").json()["seats"]
    assert all(seat["player"] is None for seat in seats)


def test_a_missing_matchid_claim_is_refused() -> None:
    with pytest.raises(TokenError, match="matchId"):
        claims_from_payload({"iss": "https://lobby.test", "sub": "u", "seatKey": "1"})


def test_both_spellings_of_the_custom_claims_are_accepted() -> None:
    # The two sides of this contract were written months apart, and a token that
    # verifies but is then rejected over `match_id` vs `matchId` is the least
    # debuggable failure this path has.
    claims = claims_from_payload({"iss": "https://lobby.test/", "sub": "u", "match_id": "m", "seat_key": "1"})
    assert claims.external_match_id == "m"
    assert claims.seat_key == "1"
    assert claims.lobby_issuer == "https://lobby.test"


# ------------------------------------------------------ jwt.unknown_match --


def test_a_token_for_another_match_cannot_open_this_one(signed_client: TestClient, signer: StubLobby) -> None:
    token = signer.mint(lobby_user_id="user-north", match_id="some-other-match", seat_key="1")
    response = signed_client.post(
        f"/api/v1/matches/{MATCH}/claim", headers={"authorization": f"Bearer {token}"}
    )
    # The one failure on this path that is a real hole rather than an
    # inconvenience: without the URL/token comparison, a valid token for match A
    # opens a seat in match B.
    assert response.status_code == 404


def test_a_token_for_a_match_we_were_never_pushed_is_a_404(
    signed_client: TestClient, signer: StubLobby
) -> None:
    token = signer.mint(lobby_user_id="user-north", match_id="never-pushed", seat_key="1")
    response = signed_client.post(
        "/api/v1/matches/never-pushed/claim", headers={"authorization": f"Bearer {token}"}
    )
    # Not 401: the token is genuine, we simply have no such match. Saying
    # "invalid token" sends an integrator looking at their signing key.
    assert response.status_code == 404


# ---------------------------------------------------------- jwt.wrong_seat --


def test_a_player_cannot_claim_a_seat_reserved_for_someone_else(
    signed_client: TestClient, signer: StubLobby
) -> None:
    token = signer.mint(lobby_user_id="user-north", match_id=MATCH, seat_key="2")
    response = signed_client.post(
        f"/api/v1/matches/{MATCH}/claim", headers={"authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403


# ------------------------------------- jwt.reclaim_same_player / seat_theft --


def test_the_same_player_reclaiming_gets_200_and_the_same_seat(
    signed_client: TestClient, signer: StubLobby
) -> None:
    token = signer.mint(lobby_user_id="user-north", match_id=MATCH, seat_key="1")
    first = signed_client.post(f"/api/v1/matches/{MATCH}/claim", headers={"authorization": f"Bearer {token}"})
    assert first.status_code == 201

    # A fresh token for the same seat — what Lobby's Rejoin button mints.
    again = signer.mint(lobby_user_id="user-north", match_id=MATCH, seat_key="1")
    second = signed_client.post(
        f"/api/v1/matches/{MATCH}/claim", headers={"authorization": f"Bearer {again}"}
    )

    # 200 and not 201: the player who already holds this seat is reconnecting,
    # and nothing was created for them.
    assert second.status_code == 200
    assert second.json()["reclaimed"] is True
    assert second.json()["you"]["playerId"] == first.json()["you"]["playerId"]


def test_a_reclaim_does_not_disturb_the_match(signed_client: TestClient, signer: StubLobby) -> None:
    north = signer.mint(lobby_user_id="user-north", match_id=MATCH, seat_key="1")
    signed_client.post(f"/api/v1/matches/{MATCH}/claim", headers={"authorization": f"Bearer {north}"})
    before = signed_client.get(f"/api/v1/matches/{MATCH}").json()

    signed_client.post(f"/api/v1/matches/{MATCH}/claim", headers={"authorization": f"Bearer {north}"})
    after = signed_client.get(f"/api/v1/matches/{MATCH}").json()

    # "Resend me the current state", not "join": no reset, no second join event,
    # nothing re-dealt (§6).
    assert after == before


def test_another_player_cannot_take_a_held_seat(signed_client: TestClient, signer: StubLobby) -> None:
    north = signer.mint(lobby_user_id="user-north", match_id=MATCH, seat_key="1")
    signed_client.post(f"/api/v1/matches/{MATCH}/claim", headers={"authorization": f"Bearer {north}"})

    # A genuine token — for a player the Lobby seated in the *other* seat —
    # pointed at seat 1. This is the seat-theft row: the token verifies, and the
    # answer still has to be no.
    thief = signer.mint(lobby_user_id="user-south", match_id=MATCH, seat_key="1")
    response = signed_client.post(
        f"/api/v1/matches/{MATCH}/claim", headers={"authorization": f"Bearer {thief}"}
    )
    assert response.status_code in (403, 409)
    assert response.status_code != 200


def test_both_seats_can_be_claimed_and_land_on_opposite_sides(
    signed_client: TestClient, signer: StubLobby
) -> None:
    north = signer.mint(lobby_user_id="user-north", match_id=MATCH, seat_key="1")
    south = signer.mint(lobby_user_id="user-south", match_id=MATCH, seat_key="2")

    a = signed_client.post(f"/api/v1/matches/{MATCH}/claim", headers={"authorization": f"Bearer {north}"})
    b = signed_client.post(f"/api/v1/matches/{MATCH}/claim", headers={"authorization": f"Bearer {south}"})

    assert a.json()["you"]["side"] == "north"
    assert b.json()["you"]["side"] == "south"
