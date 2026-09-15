"""Integration guide §8, the **Realtime** row.

    WS subscribe receives state after REST mutation

rpslr covers the same ground in `ws.test.ts`.

Two rules this file exists to hold, both of which are security properties rather
than conveniences:

* a socket acts only for the seat it holds — nothing a client sends names a side
* a dropped socket is not a player who left
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.match import fixtures
from app.service import GameService
from tests.conftest import fake_token, provision_body

MATCH = "lobby-match-1"


def _seat(client: TestClient, user: str, seat_key: str) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/matches/{MATCH}/claim",
        headers={"authorization": f"Bearer {fake_token(user, MATCH, seat_key)}"},
    )
    assert response.status_code in (200, 201), response.text
    seat: dict[str, Any] = response.json()["you"]
    return seat


def _both_seats(client: TestClient) -> tuple[dict[str, Any], dict[str, Any]]:
    client.post("/api/v1/matches", json=provision_body())
    return _seat(client, "user-north", "1"), _seat(client, "user-south", "2")


def _plan() -> dict[str, Any]:
    plan: dict[str, Any] = fixtures.opening_plan_json(1, fixtures.map_config())
    return plan


def _await_phase(ws: Any, kind: str, limit: int = 8) -> dict[str, Any]:
    """Read state pushes until one is in `kind`.

    A seat hears about its *own* lock-in before it hears about the opponent's,
    so "the next message" is not the same thing as "the state I am waiting for".
    Draining is what a real client does too — the transport is a stream, not a
    request/response pair.
    """
    for _ in range(limit):
        message = ws.receive_json()
        if message.get("type") != "state":
            continue
        if message["state"]["phase"]["kind"] == kind:
            state: dict[str, Any] = message["state"]
            return state
    raise AssertionError(f"no {kind!r} state arrived within {limit} messages")


def _await_message(ws: Any, kind: str, limit: int = 8) -> dict[str, Any]:
    """Read until a message of this type arrives, skipping state pushes."""
    for _ in range(limit):
        message = ws.receive_json()
        if message.get("type") == kind:
            found: dict[str, Any] = message
            return found
    raise AssertionError(f"no {kind!r} message arrived within {limit} messages")


def test_subscribing_delivers_an_immediate_snapshot(client: TestClient) -> None:
    north, _ = _both_seats(client)
    with client.websocket_connect("/api/v1/ws") as ws:
        ws.send_json({"type": "subscribe", "matchId": MATCH, "playerId": north["playerId"]})
        message = ws.receive_json()

    assert message["type"] == "state"
    state = message["state"]
    assert state["matchId"] == MATCH
    assert state["you"] == "north"
    assert state["phase"]["kind"] == "planning"
    assert state["testProfile"] is True


def test_a_socket_without_a_seat_is_told_so_and_gets_no_state(client: TestClient) -> None:
    _both_seats(client)
    with client.websocket_connect("/api/v1/ws") as ws:
        ws.send_json({"type": "subscribe", "matchId": MATCH, "playerId": "not-a-player"})
        message = ws.receive_json()

    assert message["type"] == "claimFailed"
    # Not retryable: this credential does not hold a seat, and no amount of
    # retrying changes that. The client shows no retry button.
    assert message["retryable"] is False


def test_an_unknown_match_is_retryable(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/ws") as ws:
        ws.send_json({"type": "subscribe", "matchId": "nope", "playerId": "x"})
        message = ws.receive_json()

    assert message["type"] == "claimFailed"
    # A socket can legitimately arrive before provision has been processed.
    assert message["retryable"] is True


def test_acting_before_subscribing_is_refused(client: TestClient) -> None:
    _both_seats(client)
    with client.websocket_connect("/api/v1/ws") as ws:
        ws.send_json(
            {"type": "cast", "cast": {"commandId": "c", "spellId": "meteor", "at": {"x": 1, "y": 1}}}
        )
        assert ws.receive_json() == {"type": "error", "error": "subscribe before acting"}


def test_a_lock_in_reaches_the_other_seats_socket(client: TestClient) -> None:
    """The row itself: a mutation on one connection reaches every subscriber."""
    north, south = _both_seats(client)

    with (
        client.websocket_connect("/api/v1/ws") as north_ws,
        client.websocket_connect("/api/v1/ws") as south_ws,
    ):
        north_ws.send_json({"type": "subscribe", "matchId": MATCH, "playerId": north["playerId"]})
        north_ws.receive_json()
        south_ws.send_json({"type": "subscribe", "matchId": MATCH, "playerId": south["playerId"]})
        south_ws.receive_json()

        north_ws.send_json({"type": "lockIn", "plan": _plan()})

        # South hears about it without having asked.
        state = south_ws.receive_json()["state"]
        assert state["phase"]["kind"] == "planning"
        # And learns nothing about what north actually planned.
        assert state["phase"]["deployment"] is None
        assert state["phase"]["locked"] is False


def test_both_seats_locking_in_starts_the_battle_over_the_socket(client: TestClient) -> None:
    north, south = _both_seats(client)

    with (
        client.websocket_connect("/api/v1/ws") as north_ws,
        client.websocket_connect("/api/v1/ws") as south_ws,
    ):
        for ws, seat in ((north_ws, north), (south_ws, south)):
            ws.send_json({"type": "subscribe", "matchId": MATCH, "playerId": seat["playerId"]})
            ws.receive_json()

        north_ws.send_json({"type": "lockIn", "plan": _plan()})
        south_ws.send_json({"type": "lockIn", "plan": _plan()})

        battle = _await_phase(north_ws, "battle")["phase"]["battle"]
        assert battle["units"]
        assert {unit["side"] for unit in battle["units"]} == {"north", "south"}
        assert "energy" in battle
        assert battle["loadout"][0]["spellId"] == "meteor"


def test_an_illegal_plan_is_answered_and_does_not_kill_the_socket(client: TestClient) -> None:
    north, _ = _both_seats(client)
    with client.websocket_connect("/api/v1/ws") as ws:
        ws.send_json({"type": "subscribe", "matchId": MATCH, "playerId": north["playerId"]})
        ws.receive_json()

        ws.send_json({"type": "lockIn", "plan": {"troops": [], "spellSlots": []}})
        rejected = ws.receive_json()
        assert rejected["type"] == "planRejected"
        assert "troop" in rejected["reason"]

        # The socket is still usable: a player mid-match must not lose their
        # connection over a refused command.
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_a_cast_is_answered_exactly_once(client: TestClient) -> None:
    north, south = _both_seats(client)

    with (
        client.websocket_connect("/api/v1/ws") as north_ws,
        client.websocket_connect("/api/v1/ws") as south_ws,
    ):
        for ws, seat in ((north_ws, north), (south_ws, south)):
            ws.send_json({"type": "subscribe", "matchId": MATCH, "playerId": seat["playerId"]})
            ws.receive_json()
        north_ws.send_json({"type": "lockIn", "plan": _plan()})
        south_ws.send_json({"type": "lockIn", "plan": _plan()})
        _await_phase(north_ws, "battle")

        north_ws.send_json(
            {
                "type": "cast",
                "cast": {"commandId": "c1", "spellId": "meteor", "at": {"x": 180, "y": 280}, "tick": 1},
            }
        )
        outcome = _await_message(north_ws, "castOutcome")
        assert outcome["commandId"] == "c1"
        assert outcome["outcome"] in ("accepted", "rejected")


def test_a_cast_can_never_be_made_for_the_other_seat(client: TestClient, service: GameService) -> None:
    """Nothing a client sends names a side, so there is nothing to forge."""
    north, south = _both_seats(client)

    with (
        client.websocket_connect("/api/v1/ws") as north_ws,
        client.websocket_connect("/api/v1/ws") as south_ws,
    ):
        for ws, seat in ((north_ws, north), (south_ws, south)):
            ws.send_json({"type": "subscribe", "matchId": MATCH, "playerId": seat["playerId"]})
            ws.receive_json()
        north_ws.send_json({"type": "lockIn", "plan": _plan()})
        south_ws.send_json({"type": "lockIn", "plan": _plan()})
        _await_phase(north_ws, "battle")

        # North tries to cast "as south", every way the payload allows.
        north_ws.send_json(
            {
                "type": "cast",
                "side": "south",
                "cast": {
                    "commandId": "forged",
                    "spellId": "meteor",
                    "at": {"x": 180, "y": 100},
                    "tick": 1,
                    "side": "south",
                    "castBy": "south",
                },
            }
        )
        outcome = _await_message(north_ws, "castOutcome")

    assert outcome["outcome"] == "accepted", "the cast is legal; only its claimed side is not"

    session = service.session(MATCH)
    assert session is not None
    casts = session.snapshot_for("north")["phase"]["battle"]["casts"]
    forged = next(cast for cast in casts if cast["commandId"] == "forged")
    # Filled in from the seat, not from anything the client said.
    assert forged["castBy"] == "north"


def test_a_malformed_cast_is_answered_without_closing_the_socket(client: TestClient) -> None:
    north, _ = _both_seats(client)
    with client.websocket_connect("/api/v1/ws") as ws:
        ws.send_json({"type": "subscribe", "matchId": MATCH, "playerId": north["playerId"]})
        ws.receive_json()

        ws.send_json({"type": "cast", "cast": {"spellId": "meteor"}})
        assert ws.receive_json()["type"] == "error"

        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_an_unknown_message_type_is_named_back(client: TestClient) -> None:
    north, _ = _both_seats(client)
    with client.websocket_connect("/api/v1/ws") as ws:
        ws.send_json({"type": "subscribe", "matchId": MATCH, "playerId": north["playerId"]})
        ws.receive_json()
        ws.send_json({"type": "teleport"})
        assert "teleport" in ws.receive_json()["error"]


def test_closing_a_socket_holds_the_seat(client: TestClient, service: GameService) -> None:
    """A dropped socket is not a player who left (integration guide §6)."""
    north, _ = _both_seats(client)

    with client.websocket_connect("/api/v1/ws") as ws:
        ws.send_json({"type": "subscribe", "matchId": MATCH, "playerId": north["playerId"]})
        ws.receive_json()

    session = service.session(MATCH)
    assert session is not None
    seat = session.seat_for_side("north")
    assert seat.connected is False, "presence is released"
    # ...and nothing else is. The seat is held, the player is expected back, and
    # the match has not ended.
    assert seat.player_id == north["playerId"]
    assert seat.departed is False
    assert session.over is False


def test_a_reconnecting_socket_gets_the_current_state_not_a_reset(
    client: TestClient, service: GameService
) -> None:
    north, south = _both_seats(client)

    with (
        client.websocket_connect("/api/v1/ws") as north_ws,
        client.websocket_connect("/api/v1/ws") as south_ws,
    ):
        for ws, seat in ((north_ws, north), (south_ws, south)):
            ws.send_json({"type": "subscribe", "matchId": MATCH, "playerId": seat["playerId"]})
            ws.receive_json()
        north_ws.send_json({"type": "lockIn", "plan": _plan()})
        south_ws.send_json({"type": "lockIn", "plan": _plan()})
        _await_phase(north_ws, "battle")

    session = service.session(MATCH)
    assert session is not None
    for _ in range(20):
        session.tick()
    tick_before = session.snapshot_for("north")["phase"]["battle"]["tick"]

    with client.websocket_connect("/api/v1/ws") as again:
        again.send_json({"type": "subscribe", "matchId": MATCH, "playerId": north["playerId"]})
        state = again.receive_json()["state"]

    # Recovery is authoritative and wholesale: the player is shown where the
    # battle actually is, not where they left it, and nothing was reset.
    assert state["phase"]["kind"] == "battle"
    assert state["phase"]["battle"]["tick"] >= tick_before


def test_invalid_json_is_answered_rather_than_fatal(client: TestClient) -> None:
    _both_seats(client)
    with client.websocket_connect("/api/v1/ws") as ws:
        ws.send_text("{not json")
        assert ws.receive_json() == {"type": "error", "error": "invalid JSON"}
