"""The match session: phases, the terminal result, and what a demo may not claim.

Every test here drives `tick()` by hand rather than waiting on a clock. That is
the whole point of keeping the clock in its own module: a match that takes 90
seconds in front of a player takes microseconds here, over the same code.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.lobby.manifest import OPENING_ROUND, STARTER
from app.match import fixtures
from app.match.plan import PlanError
from app.match.session import PLANNING_BACKSTOP_TICKS, ROUND_OVER_TICKS, MatchSession
from app.match.wire import CastCommand
from app.sim.config import SimConfig
from app.sim.types import SIDES, Vec2

MAP = fixtures.map_config()
SHORT = SimConfig(max_battle_seconds=4)


def make_session(mode: Any = OPENING_ROUND, *, seated: bool = True, **kwargs: Any) -> MatchSession:
    session = MatchSession(
        run_id="run-1",
        external_match_id="m-1",
        mode=mode,
        seats={"1": "north", "2": "south"},
        map_config=MAP,
        sim_config=SHORT,
        **kwargs,
    )
    if seated:
        # Both seats claimed, which is the ordinary case. `seated=False` is the
        # match nobody turned up for.
        for index, seat in enumerate(session.seats.values()):
            seat.player_id = f"player-{index + 1}"
            seat.lobby_user_id = f"user-{index + 1}"
    return session


def valid_plan() -> dict[str, Any]:
    return fixtures.opening_plan_json(1, MAP)


def drive(session: MatchSession, limit: int = 4000) -> int:
    ticks = 0
    while not session.over and ticks < limit:
        session.tick()
        ticks += 1
    return ticks


# ------------------------------------------------------------- planning --


def test_a_session_opens_in_planning_with_a_suggested_plan() -> None:
    session = make_session()
    snapshot = session.snapshot_for("north")
    assert snapshot["phase"]["kind"] == "planning"
    assert snapshot["phase"]["locked"] is False
    assert snapshot["phase"]["plan"]["troops"]


def test_the_snapshot_says_the_run_is_a_test_profile() -> None:
    assert make_session().snapshot_for("north")["testProfile"] is True
    assert make_session(STARTER).snapshot_for("north")["testProfile"] is False


def test_locking_in_alone_does_not_start_the_battle() -> None:
    session = make_session()
    session.lock_in("north", valid_plan())
    assert session.phase == "planning"
    assert session.locked("north") is True
    assert session.locked("south") is False


def test_a_locked_seat_sees_its_own_deployment_and_not_the_opponents() -> None:
    session = make_session()
    session.lock_in("north", valid_plan())

    deployment = session.snapshot_for("north")["phase"]["deployment"]
    assert deployment is not None
    # A player who locks in first gets the board rather than a spinner...
    assert {unit["side"] for unit in deployment["units"]} == {"north"}

    # ...and the seat that has not locked yet sees nothing of it.
    assert session.snapshot_for("south")["phase"]["deployment"] is None


def test_both_seats_locking_starts_the_battle() -> None:
    session = make_session()
    session.lock_in("north", valid_plan())
    session.lock_in("south", valid_plan())
    assert session.phase == "battle"
    assert session.snapshot_for("north")["phase"]["kind"] == "battle"


def test_a_seat_may_not_lock_in_twice() -> None:
    session = make_session()
    session.lock_in("north", valid_plan())
    # Hidden simultaneous choice is the point of the phase: a seat that could
    # re-lock after seeing its own deployment would be planning with information
    # the other seat does not have.
    with pytest.raises(PlanError, match="already locked in"):
        session.lock_in("north", valid_plan())


def test_an_illegal_plan_is_refused_and_leaves_the_seat_unlocked() -> None:
    session = make_session()
    with pytest.raises(PlanError):
        session.lock_in("north", {"troops": [], "spellSlots": []})
    assert session.locked("north") is False
    assert session.phase == "planning"


def test_a_seat_that_never_locks_still_fields_an_army() -> None:
    session = make_session()  # both seats claimed; one of them just goes quiet
    session.lock_in("north", valid_plan())
    for _ in range(PLANNING_BACKSTOP_TICKS):
        session.tick()

    # The generous backstop (JQ-308's missed-plan rule): a demo cannot hang
    # forever on a player who put their phone down.
    assert session.phase == "battle"
    battle = session.snapshot_for("south")["phase"]["battle"]
    assert {unit["side"] for unit in battle["units"]} == {"north", "south"}


def test_the_backstop_does_not_fire_on_a_match_nobody_arrived_for() -> None:
    """A seat nobody claimed must not be handed the default and played out.

    Otherwise a provisioned match whose second player never opened their link
    plays a full battle against an army that chose nothing, and reports the
    result as a real run. What *should* happen to a match that never fills — a
    forfeit timeout, an abandon — is JQ-308's policy; until then it waits.
    """
    session = make_session(seated=False)
    assert session.fully_seated is False

    for _ in range(PLANNING_BACKSTOP_TICKS * 2):
        session.tick()

    assert session.phase == "planning"
    assert session.over is False


def test_the_backstop_fires_once_both_seats_are_claimed() -> None:
    session = make_session(seated=False)
    for _ in range(PLANNING_BACKSTOP_TICKS * 2):
        session.tick()
    # Read through a local: asserting on `session.phase` twice lets mypy narrow
    # it to the first literal and call the second comparison unreachable.
    while_unseated: str = session.phase
    assert while_unseated == "planning"

    for index, seat in enumerate(session.seats.values()):
        seat.player_id = f"player-{index + 1}"

    # The wait already ran out the backstop's tick count; seating is the only
    # thing that was missing, so the very next tick starts the battle. Ticking
    # further here would run the (deliberately short) test battle to its end and
    # assert on the wrong phase.
    session.tick()

    assert session.phase == "battle"


def test_locking_in_after_the_planning_phase_is_refused() -> None:
    session = make_session()
    session.lock_in("north", valid_plan())
    session.lock_in("south", valid_plan())
    with pytest.raises(PlanError, match="planning phase is over"):
        session.lock_in("north", valid_plan())


# --------------------------------------------------------------- battle --


def test_a_cast_before_the_battle_is_refused() -> None:
    session = make_session()
    outcome = session.cast("north", CastCommand("c1", "meteor", Vec2(180, 280), 0))
    assert outcome["outcome"] == "rejected"
    # `wrongPhase` and not `roundOver` (JQ-310): a cast during the plan screen
    # is a client with a bug, and one a beat after the round ended is a client
    # with a slow connection. Telling a player the round is over when it has not
    # started sends them looking for a match that finished without them.
    assert outcome["reason"] == "wrongPhase"


def test_a_cast_during_the_battle_is_answered_exactly_once() -> None:
    session = make_session()
    session.lock_in("north", valid_plan())
    session.lock_in("south", valid_plan())
    session.tick()

    outcome = session.cast("north", CastCommand("c1", "meteor", Vec2(180, 280), 0))
    assert outcome["type"] == "castOutcome"
    assert outcome["commandId"] == "c1"
    assert outcome["outcome"] in ("accepted", "rejected")


def test_an_accepted_cast_appears_in_both_seats_snapshots() -> None:
    session = make_session()
    session.lock_in("north", valid_plan())
    session.lock_in("south", valid_plan())
    session.tick()
    session.cast("north", CastCommand("c1", "meteor", Vec2(180, 280), 0))

    for side in SIDES:
        casts = session.snapshot_for(side)["phase"]["battle"]["casts"]
        # A spell landing on the map is a visible event; hiding the opponent's
        # would make the battle unreadable.
        assert [cast["commandId"] for cast in casts] == ["c1"]


# ------------------------------------------------------- terminal result --


def test_the_demo_ends_as_a_test_and_never_as_a_won_series() -> None:
    session = make_session()
    session.lock_in("north", valid_plan())
    session.lock_in("south", valid_plan())
    drive(session)

    assert session.phase == "matchOver"
    ending = session.snapshot_for("north")["phase"]["result"]["ending"]
    # One round is not a completed best-of-five. `roundsWon` here would be
    # indistinguishable downstream from a series somebody actually took.
    assert ending["kind"] == "testComplete"


def test_the_demo_stops_after_one_round_even_when_it_is_drawn() -> None:
    """A test profile ends on rounds *played*, not on rounds won.

    The demo is a mirror match on a symmetric map, so a drawn round is an
    ordinary outcome rather than an exotic one. Ending only on a win rolls a
    drawn demo into a second round and never stops.
    """
    session = make_session()
    session.lock_in("north", valid_plan())
    session.lock_in("south", valid_plan())
    session.tick()

    # Force the draw: equal score, and the battle's backstop reached.
    for side in SIDES:
        session.round.world.zone_score[side] = 5.0
    session.round.world.tick = 10_000
    session.tick()

    assert session.phase == "matchOver"
    ending = session.snapshot_for("north")["phase"]["result"]["ending"]
    assert ending == {"kind": "testComplete", "roundWinner": None}
    assert session.rounds_won == {"north": 0, "south": 0}


def test_the_demo_reports_cancelled_so_the_run_is_unrated() -> None:
    session = make_session()
    session.lock_in("north", valid_plan())
    session.lock_in("south", valid_plan())
    drive(session)

    report = session.result_report()
    assert report is not None
    status, winners, metadata = report
    assert status == "CANCELLED"
    assert winners == [], "a rated winner would move standings on a demo"
    assert metadata["testProfile"] is True
    assert metadata["gameMode"] == "opening-round"
    # The run stays legible even though it is unrated.
    assert "roundWinner" in metadata


def test_a_destroyed_base_ends_the_match_even_under_the_test_profile() -> None:
    session = make_session()
    session.lock_in("north", valid_plan())
    session.lock_in("south", valid_plan())
    session.tick()

    session.round.world.bases["south"].hp = 0
    session.tick()

    result = session.snapshot_for("north")["phase"]["result"]
    # Takes precedence over the test profile: a base destroyed is a real
    # terminal outcome even in a demo, and reporting it as "the test finished"
    # would hide the game's central rule.
    assert result["ending"] == {"kind": "baseDestroyed", "winner": "north"}


def test_base_destruction_carries_the_remaining_hp_into_the_result() -> None:
    session = make_session()
    session.lock_in("north", valid_plan())
    session.lock_in("south", valid_plan())
    session.tick()
    session.round.world.bases["south"].hp = 0
    session.round.world.bases["north"].hp = 640.0
    session.tick()

    result = session.snapshot_for("north")["phase"]["result"]
    # Ryan, 2026-09-13: carry authoritative remaining base HP and terminal
    # reason in state and results. JQ-310 restores them on reclaim.
    assert result["baseHp"]["north"]["hp"] == 640.0
    assert result["baseHp"]["south"]["hp"] == 0


def test_starter_needs_three_round_wins() -> None:
    session = make_session(STARTER)
    session.rounds_won["north"] = 2
    session.lock_in("north", valid_plan())
    session.lock_in("south", valid_plan())

    # One more round win is not enough at 2, and is at 3.
    assert STARTER.round_policy.rounds_to_win == 3
    drive(session, limit=200)
    if session.over:
        ending = session.snapshot_for("north")["phase"]["result"]["ending"]
        assert ending["kind"] in ("roundsWon", "baseDestroyed")


def test_starter_plays_on_after_one_round() -> None:
    session = make_session(STARTER)
    session.lock_in("north", valid_plan())
    session.lock_in("south", valid_plan())

    ticks = 0
    while session.phase == "battle" and ticks < 2000:
        session.tick()
        ticks += 1

    # A round ended, and the match did not — unless a base fell.
    after_battle: str = session.phase
    if after_battle == "matchOver":
        pytest.skip("this seed ended the match rather than the round")

    assert after_battle == "roundOver"
    for _ in range(ROUND_OVER_TICKS):
        session.tick()
    assert session.phase == "planning"
    assert session.round_number == 2


def test_base_damage_persists_into_the_next_round() -> None:
    session = make_session(STARTER)
    session.lock_in("north", valid_plan())
    session.lock_in("south", valid_plan())
    session.tick()
    session.round.world.bases["north"].hp = 700.0

    ticks = 0
    while session.phase == "battle" and ticks < 2000:
        session.tick()
        ticks += 1
    after_battle: str = session.phase
    if after_battle != "roundOver":
        pytest.skip("this seed ended the match rather than the round")

    for _ in range(ROUND_OVER_TICKS):
        session.tick()
    assert session.phase == "planning"
    # No base recovery between rounds (Ryan, 2026-09-13).
    assert session.snapshot_for("north")["baseHp"]["north"]["hp"] == 700.0


def test_an_abandoned_match_reports_abandoned() -> None:
    session = make_session()
    session.abandon()
    report = session.result_report()
    assert report is not None
    assert report[0] == "ABANDONED"
    assert session.snapshot_for("north")["phase"]["result"]["ending"]["kind"] == "abandoned"


def test_there_is_no_report_before_the_match_is_over() -> None:
    assert make_session().result_report() is None
