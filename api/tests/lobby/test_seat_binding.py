"""Recovery path 1: the game's own binding, with no Lobby round trip.

Integration guide §6, *Reconnecting a player*. This is the half that keeps
working when the Lobby is slow, unreachable, or the player's Lobby session is
gone — the Rejoin button is the other half, and the two fail independently on
purpose.

The binding **names** a seat. The match **decides**.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.lobby.seat_binding import (
    SEAT_BINDING_COOKIE,
    SeatBinding,
    clear_seat_binding_cookie,
    decode_seat_binding,
    encode_seat_binding,
    seat_binding_cookie,
)
from app.service import GameService
from tests.conftest import fake_token, provision_body

MATCH = "lobby-match-1"

BINDING = SeatBinding(external_match_id="m-1", seat_key="1", lobby_user_id="user-north", player_id="player-1")


def test_a_binding_round_trips() -> None:
    assert decode_seat_binding(encode_seat_binding(BINDING)) == BINDING


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "!!!",
        "not-base64-at-all!!",
        "bm90LWpzb24",  # valid base64, "not-json" inside
        "eyJtIjogIm0tMSJ9",  # valid base64 JSON, but not a binding
        "W10",  # a JSON list, not an object
    ],
)
def test_an_unreadable_cookie_is_none_and_never_a_raise(raw: str | None) -> None:
    # A browser can present any value at all, including one left over from a
    # different deploy. An unreadable binding is an ordinary outcome of this
    # function rather than an error condition.
    assert decode_seat_binding(raw) is None


def test_a_binding_missing_a_field_is_refused() -> None:
    import base64
    import json

    partial = base64.urlsafe_b64encode(json.dumps({"m": "m-1", "s": "1"}).encode()).rstrip(b"=").decode()
    # The resume path checks all four against the match, so a binding that
    # cannot supply them is not a binding.
    assert decode_seat_binding(partial) is None


def test_the_cookie_is_httponly_and_lax() -> None:
    cookie = seat_binding_cookie(BINDING, secure=False)
    assert "HttpOnly" in cookie  # only the server ever reads it
    assert "SameSite=Lax" in cookie  # same site in every environment
    assert "Secure" not in cookie
    assert "Secure" in seat_binding_cookie(BINDING, secure=True)


def test_clearing_the_cookie_expires_it_immediately() -> None:
    assert "Max-Age=0" in clear_seat_binding_cookie(secure=False)


# ------------------------------------------------------------- the route --


def _claim(client: TestClient, user: str, seat_key: str) -> dict[str, Any]:
    """Claim a seat and return the `you` block — the seat this browser now holds."""
    response = client.post(
        f"/api/v1/matches/{MATCH}/claim",
        headers={"authorization": f"Bearer {fake_token(user, MATCH, seat_key)}"},
    )
    assert response.status_code in (200, 201), response.text
    seat: dict[str, Any] = response.json()["you"]
    return seat


def test_resume_returns_the_current_state_with_no_token(client: TestClient) -> None:
    client.post("/api/v1/matches", json=provision_body())
    seat = _claim(client, "user-north", "1")

    # No `?token=`, no Authorization header — only the cookie the claim set on
    # this game's own origin. That is the point: it still works when the Lobby
    # does not.
    response = client.get("/api/v1/resume")
    assert response.status_code == 200

    body = response.json()
    assert body["you"]["playerId"] == seat["playerId"]
    assert body["you"]["side"] == "north"
    assert body["state"]["phase"]["kind"] == "planning"


def test_resume_with_no_cookie_is_a_404(client: TestClient) -> None:
    assert client.get("/api/v1/resume").status_code == 404


def test_a_binding_naming_a_finished_match_resumes_its_terminal_state(
    client: TestClient, service: GameService
) -> None:
    """JQ-310's correction: a finished match resumes, it just cannot be played.

    The rule this replaces refused a binding whose match was over, which left a
    player whose phone slept through the last seconds of a round with a 404 —
    no result, no winner, and no way back to the Lobby. What they get instead is
    the terminal state, marked as terminal, with the return URL beside it.
    """
    client.post("/api/v1/matches", json=provision_body())
    _claim(client, "user-north", "1")

    session = service.require_session(MATCH)
    session.abandon()

    response = client.get("/api/v1/resume")
    assert response.status_code == 200

    body = response.json()
    assert body["over"] is True
    assert body["state"]["phase"]["kind"] == "matchOver"
    assert body["state"]["phase"]["result"]["ending"]["kind"] == "abandoned"
    # The way out. A result screen with no exit is where the demo ends for them.
    assert body["returnUrl"] is not None
    # The binding still works, so nothing clears it.
    assert "set-cookie" not in response.headers


def test_a_binding_naming_a_match_this_process_lost_is_cleared(
    client: TestClient, service: GameService
) -> None:
    """A session this process no longer holds still resumes nothing.

    Live match state is not persisted, so a restart really does lose the match.
    That is the case the cookie must stop being presented for — as distinct from
    a match that finished, which is still here and still worth showing.
    """
    client.post("/api/v1/matches", json=provision_body())
    _claim(client, "user-north", "1")

    service._sessions.pop(MATCH)

    response = client.get("/api/v1/resume")
    assert response.status_code == 404
    # The browser stops presenting a binding that can never work again.
    assert "Max-Age=0" in response.headers["set-cookie"]


def test_a_forged_binding_resumes_nothing(client: TestClient) -> None:
    client.post("/api/v1/matches", json=provision_body())
    _claim(client, "user-north", "1")

    forged = encode_seat_binding(
        SeatBinding(
            external_match_id=MATCH,
            seat_key="2",
            lobby_user_id="user-south",
            player_id="made-up-player-id",
        )
    )
    client.cookies.set(SEAT_BINDING_COOKIE, forged)
    # The binding names a seat; the match decides. `player_id` is checked
    # against the seat, so a forger needs a credential they could only have by
    # already being able to play that seat.
    assert client.get("/api/v1/resume").status_code == 404
