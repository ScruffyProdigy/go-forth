"""Integration guide §8, the **Lifecycle** row.

    reportMatchResult GraphQL call; return URL builder

rpslr covers the same ground in `lobbyClient.test.ts` and `lobbyReturn.test.ts`.

Plus the half JQ-309 adds on top: player identity and history persisted **keyed
by Lobby user id**, and a report that is safe to retry.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.lobby.client import LobbyClient, resolve_display_name
from app.lobby.issuer import lobby_graphql_url, lobby_issuers_match, lobby_jwks_url, normalize_lobby_issuer
from app.lobby.manifest import OPENING_ROUND, STARTER
from app.match import fixtures
from app.match.hub import MatchHub
from app.match.session import MatchSession
from app.repository import MemoryRepository
from app.service import GameService
from app.sim.config import SimConfig
from tests.conftest import RecordingLobby, fake_token, provision_body

MATCH = "lobby-match-1"


# ------------------------------------------------------------- the issuer --


def test_issuers_are_normalised_before_comparison() -> None:
    # The two sides will spell the same issuer differently — a trailing slash
    # from a config file, a query string from a copied link — and a mismatch
    # rejects every token with a message that reads like a signing problem.
    assert normalize_lobby_issuer("https://lobby.test/") == "https://lobby.test"
    assert normalize_lobby_issuer("https://lobby.test?x=1#y") == "https://lobby.test"
    assert normalize_lobby_issuer("  https://lobby.test/lobby/  ") == "https://lobby.test/lobby"
    assert lobby_issuers_match("https://lobby.test", "https://lobby.test/")


def test_unparseable_issuers_compare_rather_than_raise() -> None:
    # This is used to *compare* two issuers; a caller comparing nonsense should
    # get "these differ", not an exception on a request path.
    assert normalize_lobby_issuer("not a url/") == "not a url"
    assert normalize_lobby_issuer("") == ""


def test_both_endpoints_hang_off_the_issuer() -> None:
    assert lobby_jwks_url("https://lobby.test/") == "https://lobby.test/.well-known/jwks.json"
    assert lobby_graphql_url("https://lobby.test/") == "https://lobby.test"


# ------------------------------------------------------- reportMatchResult --


def _transport(captured: list[dict[str, Any]], response: Any = None):  # type: ignore[no-untyped-def]
    async def post(url: str, headers: Any, payload: Any) -> dict[str, Any]:
        captured.append({"url": url, "headers": dict(headers), "payload": dict(payload)})
        return response if response is not None else {"data": {"reportMatchResult": True}}

    return post


async def test_report_match_result_posts_the_mutation_with_the_service_token() -> None:
    sent: list[dict[str, Any]] = []
    client = LobbyClient("https://lobby.test/graphql", "svc-token", transport=_transport(sent))

    assert await client.report_match_result("m-1", "COMPLETED", ["winner-id"], {"gameMode": "starter"})

    assert len(sent) == 1
    assert sent[0]["headers"]["authorization"] == "Bearer svc-token"
    variables = sent[0]["payload"]["variables"]
    assert variables["matchId"] == "m-1"
    assert variables["status"] == "COMPLETED"
    assert variables["winnerLobbyUserIds"] == ["winner-id"]


async def test_a_service_token_that_already_says_bearer_is_not_doubled() -> None:
    sent: list[dict[str, Any]] = []
    client = LobbyClient("https://lobby.test", "Bearer svc", transport=_transport(sent))
    await client.report_match_result("m-1", "COMPLETED")
    assert sent[0]["headers"]["authorization"] == "Bearer svc"


@pytest.mark.parametrize(
    "response",
    [
        {"errors": [{"message": "nope"}]},
        {"data": {"reportMatchResult": False}},
        {"data": None},
        {},
    ],
)
async def test_a_failed_report_is_false_rather_than_an_exception(response: dict[str, Any]) -> None:
    client = LobbyClient("https://lobby.test", "svc", transport=_transport([], response))
    # Best effort: a match that cannot reach the Lobby still plays and still
    # tells its players what happened.
    assert await client.report_match_result("m-1", "COMPLETED") is False


async def test_a_transport_failure_is_survived() -> None:
    async def explode(url: str, headers: Any, payload: Any) -> dict[str, Any]:
        raise ConnectionError("lobby is down")

    client = LobbyClient("https://lobby.test", "svc", transport=explode)
    assert await client.report_match_result("m-1", "COMPLETED") is False
    assert await client.report_player_finished("m-1", "u", "COMPLETED") is False
    assert await client.fetch_display_name("u") is None


async def test_report_player_finished_carries_the_reason() -> None:
    sent: list[dict[str, Any]] = []
    client = LobbyClient(
        "https://lobby.test",
        "svc",
        transport=_transport(sent, {"data": {"reportPlayerFinished": True}}),
    )
    await client.report_player_finished("m-1", "u", "FORFEIT", placement=2)
    variables = sent[0]["payload"]["variables"]
    # Lobby drops `DISCONNECT` out of the rating inputs entirely, so the reason
    # is not decoration.
    assert variables["reason"] == "FORFEIT"
    assert variables["placement"] == 2


# ------------------------------------------------------------ name resolution --


async def test_the_token_name_wins_over_a_lobby_lookup() -> None:
    lobby = RecordingLobby()
    lobby.display_names["u"] = "From Lobby"
    # The token is signed, and the lookup costs a round trip on a path a player
    # is waiting on.
    resolved = await resolve_display_name(from_token="From Token", client=lobby, lobby_user_id="u")
    assert resolved == "From Token"


async def test_the_lobby_is_asked_when_the_token_is_silent() -> None:
    lobby = RecordingLobby()
    lobby.display_names["u"] = "From Lobby"
    assert await resolve_display_name(from_token=None, client=lobby, lobby_user_id="u") == "From Lobby"


async def test_there_is_always_a_name() -> None:
    assert await resolve_display_name(from_token=None, client=None, lobby_user_id="u") == "Mage"
    assert (
        await resolve_display_name(from_token="  ", client=None, lobby_user_id="u", from_body="Body")
        == "Body"
    )


# -------------------------------------------------- the session's own report --


def _finished_session(mode: Any = OPENING_ROUND, lobby: RecordingLobby | None = None) -> MatchSession:
    session = MatchSession(
        run_id="run-1",
        external_match_id=MATCH,
        mode=mode,
        seats={"1": "north", "2": "south"},
        map_config=fixtures.map_config(),
        sim_config=SimConfig(max_battle_seconds=3),
        lobby_client=lobby,
    )
    session.seat_for_side("north").lobby_user_id = "user-north"
    session.seat_for_side("south").lobby_user_id = "user-south"
    plan = fixtures.opening_plan_json(1, fixtures.map_config())
    session.lock_in("north", plan)
    session.lock_in("south", plan)
    for _ in range(3000):
        if session.over:
            break
        session.tick()
    assert session.over
    return session


async def test_a_finished_demo_reports_cancelled_and_names_no_winner() -> None:
    lobby = RecordingLobby()
    session = _finished_session(lobby=lobby)
    assert await session.report_to_lobby()

    match_id, status, winners, metadata = lobby.results[0]
    assert match_id == MATCH
    # The honest status for a run that played one round of a best-of-five.
    assert status == "CANCELLED"
    assert winners == []
    assert metadata["testProfile"] is True
    assert metadata["runId"] == "run-1"


async def test_a_demo_base_destruction_is_reported_distinctly_but_still_unrated() -> None:
    """JQ-309: *a distinct terminal base-destruction reason, without claiming a
    completed best-of-five series.*

    Both halves at once. The ending is `baseDestroyed` — not "the test
    finished" — so the run says what actually happened. The status is still
    `CANCELLED`, because one round of a best-of-five is not a series, and a
    rated result here would move standings on a demo.
    """
    lobby = RecordingLobby()
    session = MatchSession(
        run_id="run-2",
        external_match_id=MATCH,
        mode=OPENING_ROUND,
        seats={"1": "north", "2": "south"},
        map_config=fixtures.map_config(),
        sim_config=SimConfig(max_battle_seconds=30),
        lobby_client=lobby,
    )
    session.seat_for_side("north").lobby_user_id = "user-north"
    session.seat_for_side("south").lobby_user_id = "user-south"
    plan = fixtures.opening_plan_json(1, fixtures.map_config())
    session.lock_in("north", plan)
    session.lock_in("south", plan)
    session.tick()
    session.round.world.bases["south"].hp = 0
    session.round.world.bases["north"].hp = 555.0
    session.tick()

    await session.report_to_lobby()
    _match_id, status, winners, metadata = lobby.results[0]

    assert metadata["ending"] == "baseDestroyed"
    assert status == "CANCELLED"
    assert winners == []
    # Remaining base HP travels with the result (Ryan, 2026-09-13).
    assert metadata["baseHp"]["north"]["hp"] == 555.0
    assert metadata["baseHp"]["south"]["hp"] == 0


async def test_a_failed_report_leaves_the_session_unreported_for_a_retry() -> None:
    lobby = RecordingLobby()
    lobby.fail_next = True
    session = _finished_session(lobby=lobby)

    # Read through locals rather than asserting on `session.reported` twice:
    # mypy narrows a property on first comparison and then calls the second
    # branch unreachable, which would quietly delete half this test.
    first = await session.report_to_lobby()
    reported_after_failure = session.reported
    assert first is False
    assert reported_after_failure is False

    # `reportMatchResult` is keyed by match id on the Lobby's side, so the retry
    # reports the same terminal state rather than a second one.
    retry = await session.report_to_lobby()
    reported_after_retry = session.reported
    assert retry is True
    assert reported_after_retry is True
    assert len(lobby.results) == 1


# -------------------------------------------------------------- persistence --


async def test_a_finished_match_writes_one_result_row_per_player(
    repository: MemoryRepository, hub: MatchHub, lobby: RecordingLobby
) -> None:
    service = GameService(
        repository,
        hub,
        sim_config=SimConfig(max_battle_seconds=3),
        lobby_client_factory=lambda url, token: lobby,
    )
    from app.lobby.provision import parse_lobby_provision

    await service.ensure_match_from_assignment(parse_lobby_provision(provision_body()))
    session = service.require_session(MATCH)
    session.seat_for_side("north").lobby_user_id = "user-north"
    session.seat_for_side("south").lobby_user_id = "user-south"

    plan = fixtures.opening_plan_json(1, fixtures.map_config())
    session.lock_in("north", plan)
    session.lock_in("south", plan)
    for _ in range(3000):
        if session.over:
            break
        session.tick()

    await service.persist_result(session)

    for user in ("user-north", "user-south"):
        history = await service.history_for(user)
        assert len(history) == 1
        row = history[0]
        # Keyed by Lobby user id — the only identifier that is the same person
        # across matches.
        assert row.lobby_user_id == user
        assert row.test_profile is True
        assert row.ending == "testComplete"
        # NULL rather than False: "did not win" and "nobody won" are different
        # facts, and conflating them reads as a loss for both players.
        assert row.won is None


async def test_persisting_twice_does_not_stack_rows(
    repository: MemoryRepository, hub: MatchHub, lobby: RecordingLobby
) -> None:
    service = GameService(
        repository,
        hub,
        sim_config=SimConfig(max_battle_seconds=3),
        lobby_client_factory=lambda url, token: lobby,
    )
    from app.lobby.provision import parse_lobby_provision

    await service.ensure_match_from_assignment(parse_lobby_provision(provision_body()))
    session = service.require_session(MATCH)
    session.seat_for_side("north").lobby_user_id = "user-north"
    session.seat_for_side("south").lobby_user_id = "user-south"
    plan = fixtures.opening_plan_json(1, fixtures.map_config())
    session.lock_in("north", plan)
    session.lock_in("south", plan)
    for _ in range(3000):
        if session.over:
            break
        session.tick()

    await service.persist_result(session)
    await service.persist_result(session)

    # The lifecycle report is retried, so the write behind it has to be
    # idempotent in our own store as well as in the Lobby's.
    assert len(await service.history_for("user-north")) == 1
    row = repository.player_row("user-north")
    assert row is not None
    assert row["matches_played"] == 1


def test_a_player_is_recorded_at_provision_time(client: TestClient) -> None:
    client.post("/api/v1/matches", json=provision_body())
    history = client.get("/api/v1/players/user-north/history").json()
    # Known before they have finished anything, so a returning player is
    # recognised rather than created twice.
    assert history["lobbyUserId"] == "user-north"
    assert history["results"] == []


def test_history_carries_no_rating(client: TestClient) -> None:
    client.post("/api/v1/matches", json=provision_body())
    body = client.get("/api/v1/players/user-north/history").json()
    # The guide asks games not to show a player their own skill number.
    assert "skill" not in body
    assert "rating" not in body


# ------------------------------------------------------------- return URL --


def test_the_claim_hands_back_a_return_url(client: TestClient) -> None:
    client.post("/api/v1/matches", json=provision_body())
    body = client.post(
        f"/api/v1/matches/{MATCH}/claim",
        headers={"authorization": f"Bearer {fake_token('user-north', MATCH, '1')}"},
    ).json()
    assert body["returnUrl"] == f"https://joinquest.test/return?match={MATCH}"


def test_starter_would_report_completed() -> None:
    session = MatchSession(
        run_id="r",
        external_match_id=MATCH,
        mode=STARTER,
        seats={"1": "north", "2": "south"},
        map_config=fixtures.map_config(),
        sim_config=SimConfig(max_battle_seconds=3),
    )
    session.seat_for_side("north").lobby_user_id = "user-north"
    session.seat_for_side("south").lobby_user_id = "user-south"
    session.rounds_won["north"] = 3
    plan = fixtures.opening_plan_json(1, fixtures.map_config())
    session.lock_in("north", plan)
    session.lock_in("south", plan)
    for _ in range(3000):
        if session.over:
            break
        session.tick()

    report = session.result_report()
    assert report is not None
    status, winners, _metadata = report
    if status == "COMPLETED":
        # Only a real series produces a rated winner.
        assert winners == ["user-north"]
