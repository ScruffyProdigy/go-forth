"""Integration guide §8, the **Provision** row, and §11's `provision.*` checks.

    happy path + launchUrls per seat; idempotent re-push;
    reject missing/invalid Authorization

rpslr covers the same ground in `app.test.ts` and `provision.test.ts`.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.lobby.provision import ProvisionError, bearer_token, parse_lobby_provision, verify_provision_auth
from tests.conftest import BANNED_LOBBY_USER, provision_body

# ------------------------------------------------------- provision.happy_path --


def test_provision_seats_the_match_and_returns_launch_urls(client: TestClient) -> None:
    response = client.post("/api/v1/matches", json=provision_body())
    assert response.status_code == 201

    body = response.json()
    assert body["matchId"] == "lobby-match-1"
    assert body["gameMode"] == "opening-round"
    assert body["testProfile"] is True
    assert [seat["seatKey"] for seat in body["seats"]] == ["1", "2"]

    # Every seated player needs an entry or `provision.launch_urls` fails.
    assert set(body["launchUrls"]) == {"user-north", "user-south"}


def test_each_seat_is_reserved_for_its_own_lobby_user(client: TestClient) -> None:
    client.post("/api/v1/matches", json=provision_body())
    seats = client.get("/api/v1/matches/lobby-match-1").json()["seats"]
    assert seats[0]["reservedForLobbyUser"] == "user-north"
    assert seats[1]["reservedForLobbyUser"] == "user-south"


# -------------------------------------------------- provision.idempotent_repush --


def test_a_repush_returns_the_same_match_rather_than_reseating_it(client: TestClient) -> None:
    first = client.post("/api/v1/matches", json=provision_body()).json()
    second = client.post("/api/v1/matches", json=provision_body()).json()

    # The run id is the observable that would change if the match were rebuilt,
    # and rebuilding one mid-play is what this check exists to catch.
    assert second["runId"] == first["runId"]
    assert second["seats"] == first["seats"]


def test_a_repush_after_a_seat_is_claimed_keeps_the_player(client: TestClient) -> None:
    client.post("/api/v1/matches", json=provision_body())
    client.post(
        "/api/v1/matches/lobby-match-1/claim",
        headers={"authorization": "Bearer seat:user-north:lobby-match-1:1"},
    )

    body = client.post("/api/v1/matches", json=provision_body()).json()
    assert body["seats"][0]["player"] is not None, "a re-push must not evict a seated player"


# --------------------------------------------- provision.auth / missing_auth --


def test_provision_with_a_service_token_requires_a_matching_bearer(client: TestClient) -> None:
    body = provision_body(service_token="svc-secret")

    missing = client.post("/api/v1/matches", json=body)
    assert missing.status_code == 401

    wrong = client.post("/api/v1/matches", json=body, headers={"authorization": "Bearer nope"})
    assert wrong.status_code == 401

    right = client.post("/api/v1/matches", json=body, headers={"authorization": "Bearer svc-secret"})
    assert right.status_code == 201


def test_no_service_token_means_no_auth_required(client: TestClient) -> None:
    # Local dev and the stub Lobby. Without this the reference is unrunnable
    # until someone mints a token.
    assert client.post("/api/v1/matches", json=provision_body()).status_code == 201


def test_bearer_parsing_is_case_insensitive_and_trims() -> None:
    assert bearer_token("Bearer abc") == "abc"
    assert bearer_token("bearer  abc  ") == "abc"
    assert bearer_token("Basic abc") is None
    assert bearer_token("") is None
    assert bearer_token(None) is None
    assert bearer_token("Bearer   ") is None


def test_verify_auth_accepts_when_no_token_was_pushed() -> None:
    assert verify_provision_auth(None, None) is None
    assert verify_provision_auth(None, "   ") is None
    assert verify_provision_auth("Bearer x", "x") is None
    assert verify_provision_auth(None, "x") is not None


# ------------------------------------------------------ provision.banlist --


def test_a_banned_roster_is_refused_with_the_ids(client: TestClient) -> None:
    body = provision_body(
        seats=[
            {"seatKey": "1", "lobbyUserId": BANNED_LOBBY_USER},
            {"seatKey": "2", "lobbyUserId": "user-south"},
        ]
    )
    response = client.post("/api/v1/matches", json=body)
    assert response.status_code == 403
    # The exact shape Lobby parses to re-matchmake without these players.
    assert response.json()["bannedLobbyUserIds"] == [BANNED_LOBBY_USER]


def test_a_refused_provision_leaves_no_match_behind(client: TestClient) -> None:
    body = provision_body(
        external_match_id="banned-match",
        seats=[
            {"seatKey": "1", "lobbyUserId": BANNED_LOBBY_USER},
            {"seatKey": "2", "lobbyUserId": "user-south"},
        ],
    )
    client.post("/api/v1/matches", json=body)
    # Otherwise Lobby's next push finds a match it was just refused, and the
    # 403 becomes a 201 for reasons nobody can see.
    assert client.get("/api/v1/matches/banned-match").status_code == 404


# ------------------------------------------------------------- parsing rules --


def test_a_well_formed_push_parses_every_field() -> None:
    parsed = parse_lobby_provision(provision_body(service_token="svc"))
    assert parsed.lobby_id == "https://lobby.test"
    assert parsed.lobby.service_token == "svc"
    assert parsed.assignment.external_match_id == "lobby-match-1"
    assert parsed.lobby_user_ids == ("user-north", "user-south")
    assert parsed.assignment.seats[0].display_name == "North"


def test_skill_is_read_but_never_reaches_the_wire() -> None:
    body = provision_body(
        seats=[
            {"seatKey": "1", "lobbyUserId": "a", "skill": {"rating": 31.5, "uncertainty": 2.25}},
            {"seatKey": "2", "lobbyUserId": "b"},
        ]
    )
    parsed = parse_lobby_provision(body)
    assert parsed.assignment.seats[0].skill is not None
    assert parsed.assignment.seats[0].skill.rating == 31.5
    # The guide asks games not to show players a rating; the surest way to
    # honour that is for no client-facing schema to carry one.
    assert parsed.assignment.seats[1].skill is None


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda b: b.pop("lobbyId"), "lobbyId is required"),
        (lambda b: b.pop("lobby"), "lobby is required"),
        (lambda b: b["lobby"].pop("returnUrl"), "lobby.returnUrl is required"),
        (lambda b: b["lobby"].pop("graphqlUrl"), "lobby.graphqlUrl is required"),
        (lambda b: b.pop("assignment"), "assignment is required"),
        (lambda b: b["assignment"].pop("externalMatchId"), "assignment.externalMatchId is required"),
        (lambda b: b["assignment"].pop("gameMode"), "assignment.gameMode is required"),
        (lambda b: b["assignment"].update(seats=[]), "assignment.seats must be a non-empty array"),
        (lambda b: b["assignment"]["seats"][0].pop("seatKey"), "each seat requires seatKey"),
        (lambda b: b["assignment"]["seats"][0].pop("lobbyUserId"), "each seat requires lobbyUserId"),
        (lambda b: b["assignment"].update(bestOf="five"), "assignment.bestOf must be a number"),
    ],
)
def test_a_malformed_push_names_what_is_wrong(mutate, expected: str) -> None:  # type: ignore[no-untyped-def]
    body = provision_body()
    mutate(body)
    with pytest.raises(ProvisionError, match=expected):
        parse_lobby_provision(body)


def test_duplicate_seat_keys_are_refused() -> None:
    body = provision_body(
        seats=[
            {"seatKey": "1", "lobbyUserId": "a"},
            {"seatKey": "1", "lobbyUserId": "b"},
        ]
    )
    # Two players in one seat is not a state the session can represent, and
    # accepting it would silently drop one of them.
    with pytest.raises(ProvisionError, match="repeats seatKey"):
        parse_lobby_provision(body)


def test_a_malformed_body_is_a_400_not_a_crash(client: TestClient) -> None:
    response = client.post("/api/v1/matches", json={"assignment": {"seats": "nope"}})
    assert response.status_code == 400
    assert "error" in response.json()
