"""Getting back in: what a reclaim shows, and what it must never show.

Two recovery paths, and they are tested apart because they **fail apart**
(integration guide §6, and the reason JQ-310 asks for them separately):

* **path 1 — refresh, from the game's own origin.** A cookie this game wrote on
  its own domain, checked against the live match. No Lobby round trip, so it
  still works when the Lobby is slow, unreachable, or the player's Lobby session
  has expired. `GET /api/v1/resume`.
* **path 2 — the Lobby's Rejoin button.** A fresh seat token, claimed again.
  Works from a different browser, a different device, or after the cookie is
  gone. `POST /api/v1/matches/{id}/claim`.

A player who cannot get back in ruins the match for the person still in it, so
neither path is allowed to be the only one.

The third thing here is what a reclaim is **not**: a reveal. Coming back must
not show a returning player anything a player who never left could not see, and
the opponent's unlocked plan is the whole mechanic of the planning phase.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.lobby.manifest import OPENING_ROUND
from app.match import fixtures
from app.match.session import MatchSession
from app.match.wire import CastCommand
from app.service import GameService
from app.sim.config import SimConfig
from app.sim.types import SIDES, Side, Vec2
from tests.conftest import RecordingLobby, fake_token, provision_body

MATCH = "lobby-match-1"
MAP = fixtures.map_config()
SHORT = SimConfig(max_battle_seconds=6)


def make_session() -> MatchSession:
    session = MatchSession(
        run_id="run-1",
        external_match_id="m-1",
        mode=OPENING_ROUND,
        seats={"1": "north", "2": "south"},
        map_config=MAP,
        sim_config=SHORT,
    )
    for index, seat in enumerate(session.seats.values()):
        seat.player_id = f"player-{index + 1}"
        seat.lobby_user_id = f"user-{index + 1}"
    return session


def suggested_plan() -> dict[str, Any]:
    return fixtures.opening_plan_json(1, MAP)


def lone_troop_plan() -> dict[str, Any]:
    """A plan that is unmistakably not the suggested default.

    One troop instead of three, and no spell. A reclaim test that used the
    default could not tell "we gave you back your plan" from "we gave you back
    the suggestion", which is precisely the bug it is looking for.
    """
    return {
        "troops": [{"mageId": "ember-adept", "summonIds": ["cinder-hound"], "order": {"kind": "defendBase"}}],
        "spellSlots": [None, None],
    }


def claim(client: TestClient, user: str, seat_key: str) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/matches/{MATCH}/claim",
        headers={"authorization": f"Bearer {fake_token(user, MATCH, seat_key)}"},
    )
    assert response.status_code in (200, 201), response.text
    seat: dict[str, Any] = response.json()["you"]
    return seat


# ------------------------------------------------- what a reclaim has to carry --


def test_a_reclaim_during_planning_returns_the_plan_the_player_locked_in() -> None:
    """The half of reclaim that is easy to miss, because nothing looks broken.

    Without it a player who refreshes after locking in is shown the suggested
    default, concludes their lock-in vanished, and re-plans a round the server
    has already accepted their army for.
    """
    session = make_session()
    session.lock_in("north", lone_troop_plan())

    phase = session.snapshot_for("north")["phase"]

    assert phase["kind"] == "planning"
    assert phase["locked"] is True
    assert [troop["mageId"] for troop in phase["plan"]["troops"]] == ["ember-adept"]
    assert phase["plan"]["spellSlots"] == [None, None]
    # The screen is still a screen: the roster it is built from comes with it.
    assert phase["plan"]["roster"]["mages"]


def test_a_seat_that_has_not_locked_still_sees_the_suggested_default() -> None:
    session = make_session()
    phase = session.snapshot_for("north")["phase"]
    assert phase["locked"] is False
    assert len(phase["plan"]["troops"]) == fixtures.MAGE_CAP


def test_a_reclaim_during_planning_carries_the_resolved_loadout_and_energy() -> None:
    """Resolved by the server, and known before the battle rather than during it.

    A client that priced spells off the card would let a player spend energy
    they do not have; one that learned the price only when the battle started
    would render a plan screen it could not check.
    """
    session = make_session()
    session.lock_in("north", suggested_plan())

    phase = session.snapshot_for("north")["phase"]
    assert [spell["spellId"] for spell in phase["loadout"]] == ["meteor"]
    assert phase["loadout"][0]["cost"] > 0
    assert phase["energy"] == fixtures.STARTING_ENERGY


def test_a_reclaim_mid_battle_carries_the_whole_of_what_the_seat_may_know() -> None:
    session = make_session()
    session.lock_in("north", suggested_plan())
    session.lock_in("south", suggested_plan())
    for _ in range(10):
        session.tick()

    snapshot = session.snapshot_for("north")

    # Identity of the run, so a client can tell a reconnect from a new match.
    assert snapshot["runId"] == "run-1"
    assert snapshot["you"] == "north"
    # The round tally and the test-profile label are the server's claim about
    # this run, not a build-time constant in the client.
    assert snapshot["round"] == 1
    assert snapshot["roundsWon"] == {side: 0 for side in SIDES}
    assert snapshot["testProfile"] is True
    # Remaining base HP, both sides (Ryan, 2026-09-13).
    assert set(snapshot["baseHp"]) == set(SIDES)
    assert snapshot["baseHp"]["north"]["hp"] > 0

    battle = snapshot["phase"]["battle"]
    assert battle["units"]
    assert battle["tick"] > 0
    assert battle["energy"] > 0
    assert [spell["spellId"] for spell in battle["loadout"]] == ["meteor"]
    assert battle["casts"] == []


def test_a_reclaim_never_replays_accepted_commands() -> None:
    """Coming back shows a cast that landed; it does not cast it again."""
    session = make_session()
    session.lock_in("north", suggested_plan())
    session.lock_in("south", suggested_plan())
    session.tick()
    assert session.cast("north", CastCommand("c1", "meteor", Vec2(180, 280), 0))["outcome"] == "accepted"

    energy = session.round.energy_for("north")
    # Five reclaims in a row — a client in a reconnect loop.
    snapshots = [session.snapshot_for("north") for _ in range(5)]

    for snapshot in snapshots:
        assert len(snapshot["phase"]["battle"]["casts"]) == 1
    assert session.round.energy_for("north") == energy


# --------------------------------------------------------- hidden stays hidden --


def test_a_reclaim_during_planning_shows_nothing_of_the_opponent() -> None:
    """Hidden simultaneous choice is the plan phase's whole mechanic.

    Checked against the payload rather than against what a UI draws: a field a
    client merely declines to render is still a field in the network tab.
    """
    session = make_session()
    session.lock_in("south", lone_troop_plan())

    phase = session.snapshot_for("north")["phase"]

    assert phase["locked"] is False, "north's own lock state, not south's"
    assert phase["deployment"] is None
    assert len(phase["plan"]["troops"]) == fixtures.MAGE_CAP, "the suggestion, not south's plan"
    assert "defendBase" not in repr(phase), "nothing of south's order anywhere in the payload"


def test_the_reveal_is_the_battle_starting() -> None:
    session = make_session()
    session.lock_in("south", lone_troop_plan())
    assert session.snapshot_for("north")["phase"]["deployment"] is None

    session.lock_in("north", suggested_plan())
    battle = session.snapshot_for("north")["phase"]["battle"]

    # Now both armies are on the field, because both plans are committed.
    assert {unit["side"] for unit in battle["units"]} == set(SIDES)


def test_a_reclaim_mid_battle_carries_no_opponent_energy() -> None:
    session = make_session()
    session.lock_in("north", suggested_plan())
    session.lock_in("south", suggested_plan())
    session.tick()

    north = session.snapshot_for("north")["phase"]["battle"]

    # One energy number, and it is this seat's own. Knowing the opponent's tells
    # you exactly which spell is coming, so there is nowhere in the payload it
    # could be read from — not a second field, not a list, not a pair.
    assert isinstance(north["energy"], float)
    assert [key for key in north if "nergy" in key] == ["energy"]


# ------------------------------------------------- path 1: refresh, own origin --


def test_refresh_recovery_needs_no_lobby_and_no_token(client: TestClient) -> None:
    client.post("/api/v1/matches", json=provision_body())
    seat = claim(client, "user-north", "1")

    # No Authorization header, no `?token=`. Just the cookie the claim wrote.
    response = client.get("/api/v1/resume")

    assert response.status_code == 200
    body = response.json()
    assert body["you"]["playerId"] == seat["playerId"]
    assert body["you"]["side"] == "north"
    assert body["over"] is False
    assert body["state"]["phase"]["kind"] == "planning"


def test_refresh_recovery_returns_the_players_own_locked_plan(
    client: TestClient, service: GameService
) -> None:
    client.post("/api/v1/matches", json=provision_body())
    claim(client, "user-north", "1")
    service.require_session(MATCH).lock_in("north", lone_troop_plan())

    phase = client.get("/api/v1/resume").json()["state"]["phase"]

    assert phase["locked"] is True
    assert [troop["mageId"] for troop in phase["plan"]["troops"]] == ["ember-adept"]


def test_a_binding_resumes_only_the_seat_it_was_issued_for(client: TestClient) -> None:
    """The binding names a seat; the match decides.

    Path 1's whole security argument is that the cookie grants nothing the
    client did not already hold, because every field in it is re-checked against
    the live match before anything resumes. Here that means a browser holding
    north's binding gets north's seat and north's view — never south's, even
    once south is sitting in the same match.
    """
    client.post("/api/v1/matches", json=provision_body())
    claim(client, "user-north", "1")
    north_cookie = client.cookies.get("go_forth_seat")
    assert north_cookie is not None

    # South claims from their own browser and gets their own binding.
    claim(client, "user-south", "2")

    presenting_north = TestClient(client.app)
    presenting_north.cookies.set("go_forth_seat", north_cookie)
    body = presenting_north.get("/api/v1/resume").json()

    assert body["you"]["seatKey"] == "1"
    assert body["you"]["side"] == "north"
    assert body["state"]["you"] == "north"


# ----------------------------------------------------- path 2: the Lobby rejoin --


def test_the_same_player_may_reclaim_their_seat(client: TestClient) -> None:
    client.post("/api/v1/matches", json=provision_body())
    first = claim(client, "user-north", "1")

    again = client.post(
        f"/api/v1/matches/{MATCH}/claim",
        headers={"authorization": f"Bearer {fake_token('user-north', MATCH, '1')}"},
    )

    # 200 and not 201: nothing was created, they were already sitting here.
    assert again.status_code == 200
    body = again.json()
    assert body["reclaimed"] is True
    assert body["you"]["playerId"] == first["playerId"], "the same credential, so their state is theirs"
    assert body["you"]["side"] == "north"


def test_another_player_may_not_take_a_held_seat(client: TestClient) -> None:
    client.post("/api/v1/matches", json=provision_body())
    claim(client, "user-north", "1")

    stolen = client.post(
        f"/api/v1/matches/{MATCH}/claim",
        headers={"authorization": f"Bearer {fake_token('user-south', MATCH, '1')}"},
    )

    # 403 and not 409: seat 1 is *reserved* for user-north by the assignment, so
    # this is refused before occupancy even comes into it.
    assert stolen.status_code == 403


def test_the_two_paths_are_independent(client: TestClient) -> None:
    """Path 2 works with no cookie at all — a different device, or a cleared one."""
    client.post("/api/v1/matches", json=provision_body())
    claim(client, "user-north", "1")

    fresh = TestClient(client.app)
    assert fresh.get("/api/v1/resume").status_code == 404, "no cookie, so path 1 has nothing"

    rejoined = fresh.post(
        f"/api/v1/matches/{MATCH}/claim",
        headers={"authorization": f"Bearer {fake_token('user-north', MATCH, '1')}"},
    )
    assert rejoined.status_code == 200
    assert rejoined.json()["reclaimed"] is True


# -------------------------------------------------------------- terminal state --


def destroy_base(session: MatchSession, side: Side) -> None:
    """Take a base to zero mid-battle, the way a committed push would."""
    session.round.world.bases[side].hp = 0.0
    session.tick()


def test_a_destroyed_base_ends_the_match_and_reclaim_does_not_heal_it() -> None:
    """Ryan, 2026-09-13: refresh cannot restore HP or resume a destroyed base."""
    session = make_session()
    session.lock_in("north", suggested_plan())
    session.lock_in("south", suggested_plan())
    session.tick()

    destroy_base(session, "south")

    assert session.over is True
    for _ in range(3):
        # Reclaiming repeatedly, as a client in a reconnect loop would.
        snapshot = session.snapshot_for("south")
        assert snapshot["baseHp"]["south"]["hp"] == 0
        assert snapshot["phase"]["kind"] == "matchOver"
        ending = snapshot["phase"]["result"]["ending"]
        assert ending["kind"] == "baseDestroyed"
        assert ending["winner"] == "north"
    assert session.run_record.terminal_reason == "baseDestroyed"


def test_a_terminal_reconnect_returns_the_result_and_the_way_back(
    client: TestClient, service: GameService
) -> None:
    """The worst moment in the demo to hand somebody a 404.

    A player whose phone slept through the last seconds of a round comes back to
    a finished match. What they need is who won and a way out, and both are here
    rather than behind a Lobby round trip they may not be able to make.
    """
    client.post("/api/v1/matches", json=provision_body())
    claim(client, "user-north", "1")
    service.require_session(MATCH).abandon(winner="north")

    body = client.get("/api/v1/resume").json()

    assert body["over"] is True
    assert body["state"]["phase"]["kind"] == "matchOver"
    assert body["returnUrl"].startswith("https://joinquest.test/return")


def test_reconnecting_over_the_socket_after_the_match_is_over_shows_the_result(
    client: TestClient, service: GameService
) -> None:
    client.post("/api/v1/matches", json=provision_body())
    seat = claim(client, "user-north", "1")
    claim(client, "user-south", "2")
    service.require_session(MATCH).abandon()

    with client.websocket_connect("/api/v1/ws") as ws:
        ws.send_json({"type": "subscribe", "matchId": MATCH, "playerId": seat["playerId"]})
        state = ws.receive_json()["state"]

    assert state["phase"]["kind"] == "matchOver"
    assert state["phase"]["result"]["ending"]["kind"] == "abandoned"


# ----------------------------------------------- a dropped socket is not a exit --


def test_a_dropped_socket_never_reports_the_player_finished(
    client: TestClient, service: GameService, lobby: RecordingLobby
) -> None:
    """Integration guide §6, and the one recovery rule with a Lobby side effect.

    `reportPlayerFinished` takes a player out of a match. Calling it for a
    socket that closed would take them out of one they are still in — at the
    moment they are least able to say so.
    """
    client.post("/api/v1/matches", json=provision_body())
    seat = claim(client, "user-north", "1")
    claim(client, "user-south", "2")

    for _ in range(3):
        with client.websocket_connect("/api/v1/ws") as ws:
            ws.send_json({"type": "subscribe", "matchId": MATCH, "playerId": seat["playerId"]})
            ws.receive_json()

    assert lobby.finished == []
    session = service.require_session(MATCH)
    assert session.seat_for_side("north").departed is False
    assert session.over is False


def test_the_battle_runs_on_while_a_seat_is_away() -> None:
    """Losing a connection does not pause the game for the player still playing."""
    session = make_session()
    session.lock_in("north", suggested_plan())
    session.lock_in("south", suggested_plan())
    session.tick()

    session.seat_for_side("north").connected = False
    before = session.round.world.tick
    for _ in range(20):
        session.tick()

    assert session.round.world.tick > before
    assert session.seat_for_side("north").player_id is not None, "and the seat is still theirs"
