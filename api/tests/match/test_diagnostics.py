"""Diagnostics: two channels, kept apart, carrying no credentials.

JQ-310: *separate rejected-command/reconnect and selected AI diversion/return
diagnostics; no secrets.*

The demo's two failure stories are "my spell didn't go off" and "I got kicked
out". Neither is answerable from a battle log, and both are decisions the server
made — about a **command** or about a **connection**. Those are the channels,
and the separation is the point: "fourteen casts were refused for `stale`" and
"one player reconnected fourteen times" are different findings with different
fixes, and one interleaved stream makes each look like noise in the other.

AI diversion and return diagnostics are JQ-331's and stay in JQ-331's own sink.
Why a *unit* changed its mind is a question about the evaluator, answered against
a scenario; why a *command* was refused is a question about one socket at one
moment.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.lobby.manifest import OPENING_ROUND
from app.match import fixtures
from app.match.diagnostics import DiagnosticsLog, SecretInDiagnostic, redacted
from app.match.session import MatchSession
from app.match.wire import CastCommand
from app.service import GameService
from app.sim.config import SimConfig
from app.sim.types import Vec2
from tests.conftest import fake_token, provision_body

MATCH = "lobby-match-1"
MAP = fixtures.map_config()
SHORT = SimConfig(max_battle_seconds=3)


def make_session(diagnostics: DiagnosticsLog | None = None) -> MatchSession:
    session = MatchSession(
        run_id="run-1",
        external_match_id="m-1",
        mode=OPENING_ROUND,
        seats={"1": "north", "2": "south"},
        map_config=MAP,
        sim_config=SHORT,
        diagnostics=diagnostics,
    )
    for index, seat in enumerate(session.seats.values()):
        seat.player_id = f"player-{index + 1}"
        seat.lobby_user_id = f"user-{index + 1}"
    return session


def in_battle(session: MatchSession) -> MatchSession:
    plan = fixtures.opening_plan_json(1, MAP)
    session.lock_in("north", plan)
    session.lock_in("south", plan)
    session.tick()
    return session


def claim(client: TestClient, user: str, seat_key: str) -> str:
    response = client.post(
        f"/api/v1/matches/{MATCH}/claim",
        headers={"authorization": f"Bearer {fake_token(user, MATCH, seat_key)}"},
    )
    assert response.status_code in (200, 201), response.text
    player_id: str = response.json()["you"]["playerId"]
    return player_id


# ------------------------------------------------------------ no credentials --


@pytest.mark.parametrize(
    "field",
    ["player_id", "playerId", "lobbyPlayerId", "service_token", "serviceToken", "jwt", "cookie", "secret"],
)
def test_a_field_that_would_carry_a_credential_is_refused(field: str) -> None:
    """Refused at the door rather than documented.

    `player_id` is the one that matters: it is not an identifier, it is *the
    gameplay credential* — the WebSocket subscribes with it and the seat binding
    is checked against it — so a diagnostic carrying one seats its reader. A rule
    that is only written down holds until the first hurried addition.
    """
    log = DiagnosticsLog()
    with pytest.raises(SecretInDiagnostic):
        log.record(channel="command", kind="command.rejected", match_id="m", run_id="r", **{field: "x"})


def test_naming_a_seat_is_allowed_because_a_seat_is_a_chair() -> None:
    log = DiagnosticsLog()
    event = log.record(
        channel="connection",
        kind="connection.dropped",
        match_id="m",
        run_id="r",
        seat_key="1",
        side="north",
    )
    assert event.to_json()["seat_key"] == "1"
    assert redacted(["seat_key", "side", "reason", "phase"]) == []


def test_a_whole_run_of_diagnostics_names_no_player_and_no_token(
    client: TestClient, service: GameService
) -> None:
    """The end-to-end version of the rule, over everything a real run emits."""
    client.post("/api/v1/matches", json=provision_body())
    north = claim(client, "user-north", "1")
    claim(client, "user-south", "2")

    with client.websocket_connect("/api/v1/ws") as ws:
        ws.send_json({"type": "subscribe", "matchId": MATCH, "playerId": north})
        ws.receive_json()
    client.get("/api/v1/resume")

    events = service.diagnostics.events(MATCH)
    assert events, "a run with a claim and a socket in it emits something"

    payload = repr([event.to_json() for event in events])
    assert north not in payload
    assert "user-north" not in payload, "the Lobby user id is not ours to scatter about either"


# ---------------------------------------------------------- the command channel --


def test_a_refused_cast_is_recorded_with_its_reason() -> None:
    session = in_battle(make_session())
    session.cast("north", CastCommand("c1", "meteor", Vec2(-5, -5), 0))

    (event,) = session.diagnostics.events("m-1", channel="command")
    assert event.kind == "command.rejected"
    assert event.fields["reason"] == "outOfBounds"
    assert event.fields["side"] == "north"
    assert event.fields["phase"] == "battle"
    assert event.fields["round"] == 1
    assert event.run_id == "run-1"


def test_an_accepted_cast_is_not_a_diagnostic() -> None:
    """The channel is for decisions that surprised somebody.

    An accepted cast is in the run record, in the snapshot, and on the client's
    screen. Logging it here too would bury the refusals among them, which is the
    one thing this channel exists to make findable.
    """
    session = in_battle(make_session())
    assert session.cast("north", CastCommand("c1", "meteor", Vec2(180, 280), 0))["outcome"] == "accepted"
    assert session.diagnostics.events("m-1", channel="command") == []


def test_a_retry_is_recorded_as_a_retry_and_not_as_a_new_decision() -> None:
    """A reconnect storm and a rejection storm must not read the same.

    A client resending after a lost acknowledgment is a *connection* problem
    showing up on the command channel, and a diagnostic that filed it as a fresh
    rejection would have an operator looking at the cast rules.
    """
    session = in_battle(make_session())
    session.cast("north", CastCommand("c1", "meteor", Vec2(180, 280), 0))
    for _ in range(3):
        session.cast("north", CastCommand("c1", "meteor", Vec2(180, 280), 0))

    kinds = [event.kind for event in session.diagnostics.events("m-1", channel="command")]
    assert kinds == ["command.retried"] * 3
    assert session.diagnostics.summary("m-1") == {"command.retried": 3}


def test_a_retried_rejection_says_what_it_was_answered_with() -> None:
    session = in_battle(make_session())
    session.cast("north", CastCommand("c1", "meteor", Vec2(-5, -5), 0))
    session.cast("north", CastCommand("c1", "meteor", Vec2(-5, -5), 0))

    retried = session.diagnostics.events("m-1", channel="command")[-1]
    assert retried.kind == "command.retried"
    assert retried.fields["outcome"] == "rejected"
    assert retried.fields["reason"] == "outOfBounds"


# -------------------------------------------------------- the connection channel --


def test_arriving_returning_and_dropping_are_three_different_events(
    client: TestClient, service: GameService
) -> None:
    client.post("/api/v1/matches", json=provision_body())
    north = claim(client, "user-north", "1")

    for _ in range(2):
        with client.websocket_connect("/api/v1/ws") as ws:
            ws.send_json({"type": "subscribe", "matchId": MATCH, "playerId": north})
            ws.receive_json()

    kinds = [event.kind for event in service.diagnostics.events(MATCH, channel="connection")]
    assert kinds == [
        "connection.seated",  # the claim
        "connection.subscribed",  # first socket
        "connection.dropped",
        "connection.reconnected",  # second socket, and it says so
        "connection.dropped",
    ]


def test_the_two_recovery_paths_are_told_apart(client: TestClient, service: GameService) -> None:
    """They fail independently, so a diagnostic that could not tell them apart
    could not say which one was broken."""
    client.post("/api/v1/matches", json=provision_body())
    claim(client, "user-north", "1")
    client.get("/api/v1/resume")
    client.post(
        f"/api/v1/matches/{MATCH}/claim",
        headers={"authorization": f"Bearer {fake_token('user-north', MATCH, '1')}"},
    )

    paths = [
        (event.kind, event.fields.get("path"))
        for event in service.diagnostics.events(MATCH, channel="connection")
    ]
    assert ("connection.seated", "lobbyToken") in paths
    assert ("connection.resumed", "seatBinding") in paths
    assert ("connection.reclaimed", "lobbyToken") in paths


def test_a_socket_turned_away_from_a_seat_is_recorded(client: TestClient, service: GameService) -> None:
    client.post("/api/v1/matches", json=provision_body())
    claim(client, "user-north", "1")

    with client.websocket_connect("/api/v1/ws") as ws:
        ws.send_json({"type": "subscribe", "matchId": MATCH, "playerId": "not-a-player"})
        assert ws.receive_json()["type"] == "claimFailed"

    refused = [
        event
        for event in service.diagnostics.events(MATCH, channel="connection")
        if event.kind == "connection.refused"
    ]
    assert len(refused) == 1
    assert refused[0].fields["reason"] == "notYourSeat"
    assert refused[0].fields["retryable"] is False


# ------------------------------------------------------------- the log itself --


def test_the_channels_are_readable_apart() -> None:
    session = in_battle(make_session())
    session.cast("north", CastCommand("c1", "meteor", Vec2(-5, -5), 0))
    session.note_connection("connection.dropped", seat_key="1", side="north")

    log = session.diagnostics
    assert {event.channel for event in log.events("m-1", channel="command")} == {"command"}
    assert {event.channel for event in log.events("m-1", channel="connection")} == {"connection"}
    assert len(log.events("m-1")) == 2


def test_matches_do_not_share_a_stream() -> None:
    log = DiagnosticsLog()
    first = make_session(log)
    second = make_session(log)
    second.external_match_id = "m-2"

    first.note_connection("connection.dropped", seat_key="1", side="north")
    second.note_connection("connection.dropped", seat_key="1", side="north")

    assert len(log.events("m-1")) == 1
    assert len(log.events("m-2")) == 1
    assert list(log) == ["m-1", "m-2"], "sorted: nothing here may leak dict order"


def test_the_log_is_bounded() -> None:
    """A deque behind a socket a client controls, with a retry loop attached."""
    log = DiagnosticsLog(max_events=8)
    for index in range(100):
        log.record(channel="command", kind="command.rejected", match_id="m", run_id="r", seq=index)

    events = log.events("m")
    assert len(events) == 8
    assert [event.fields["seq"] for event in events] == list(range(92, 100)), "the newest are kept"


def test_forgetting_a_match_drops_its_events() -> None:
    log = DiagnosticsLog()
    log.record(channel="command", kind="command.rejected", match_id="m", run_id="r")
    log.forget("m")
    assert log.events("m") == []
