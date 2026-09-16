"""Command ids, deduplication, and what the server decides about a cast.

JQ-310's first acceptance criterion, in one file: *validate seat, phase, schema
and command id; deduplicate retries, reject stale/wrong-phase casts, assign
accepted tick/order on server. One accepted command spends energy once.*

The seat half is `test_realtime.py`'s — a socket acts only for the seat it
holds, and nothing a client sends names a side. The schema half is
`test_wire.py`'s. What is here is everything that happens after a well-formed
cast has been attributed to a seat.

**The story every test below is about.** A phone on a train loses
acknowledgments, not commands. A client that hears nothing resends, because from
where it is sitting nothing happened. If the server counts that as a second cast
the player pays twice for one meteor, and there is nothing they could have done
differently.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.lobby.manifest import OPENING_ROUND
from app.match import fixtures
from app.match.commands import CommandLedger, LedgerEntry
from app.match.plan import default_plan, resolve_loadout
from app.match.round import STALE_COMMAND_TICKS, AuthoritativeRound
from app.match.session import MatchSession
from app.match.wire import MAX_COMMAND_ID_LENGTH, CastCommand, CommandError, parse_cast_command
from app.sim.config import SimConfig
from app.sim.types import SIDES, Vec2

MAP = fixtures.map_config()
SHORT = SimConfig(max_battle_seconds=6)

#: On the map and clear of both bases, so a cast is refused for the reason a
#: test is about rather than for being out of bounds.
ON_MAP = Vec2(180, 280)


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


def in_battle() -> MatchSession:
    session = make_session()
    plan = fixtures.opening_plan_json(1, MAP)
    session.lock_in("north", plan)
    session.lock_in("south", plan)
    session.tick()
    return session


def cast(command_id: str, *, tick: int = 0, at: Vec2 = ON_MAP) -> CastCommand:
    return CastCommand(command_id=command_id, spell_id="meteor", at=at, tick=tick)


def rich_round(*, energy: float = 400.0, seconds: float = 20) -> AuthoritativeRound:
    """A round with energy to spare, for the tests that need several casts."""
    plan = default_plan(MAP)
    loadout = resolve_loadout(plan)
    return AuthoritativeRound(
        round_number=1,
        map_config=MAP,
        plans={side: plan for side in SIDES},
        loadouts={side: loadout for side in SIDES},
        base_hp={side: 1000.0 for side in SIDES},
        seed=5,
        sim_config=SimConfig(max_battle_seconds=seconds),
        starting_energy=energy,
    )


# ------------------------------------------------------- deduplicated retries --


def test_a_retried_cast_is_answered_identically_and_spends_energy_once() -> None:
    """The lost-acknowledgment case, which is the reason the ledger exists."""
    session = in_battle()

    first = session.cast("north", cast("c1"))
    assert first["outcome"] == "accepted"
    after_first = session.round.energy_for("north")

    # The client heard nothing and sent the very same command again.
    again = session.cast("north", cast("c1"))

    assert again == first, "a retry is answered with the answer, not with a new one"
    assert session.round.energy_for("north") == after_first, "one accepted command, one spend"
    assert len(session.round.casts()) == 1, "and one spell in the world"


def test_a_retry_that_arrives_after_the_round_ended_still_reports_the_acceptance() -> None:
    """The most likely moment for a retry is the worst one to get wrong.

    A socket that dropped mid-battle reconnects some seconds later, which may
    well be after the round finished. A ledger scoped to the round would have
    been thrown away by then, and the retry would be answered `roundOver` —
    telling a player their meteor failed when it had already landed.
    """
    session = in_battle()
    accepted = session.cast("north", cast("c1"))
    assert accepted["outcome"] == "accepted"

    while not session.over:
        session.tick()

    assert session.cast("north", cast("c1")) == accepted


def test_a_rejected_command_id_stays_rejected() -> None:
    """A command id's answer is final, and that is the rule a client is built on.

    Re-evaluating on retry would mean the same id could be refused once and
    accepted later — so a client that resent on a timeout could turn a refusal
    into a cast it never got told about. A player who wants another go taps
    again, and the client mints a new id for it.
    """
    session = in_battle()

    refused = session.cast("north", cast("c1", at=Vec2(-50, -50)))
    assert refused["reason"] == "outOfBounds"

    assert session.cast("north", cast("c1")) == refused, "even a legal retry under a spent id"


def test_two_seats_may_mint_the_same_command_id() -> None:
    """Client-minted ids are unique per client, not per match.

    Two phones independently minting `c1` is ordinary. A ledger keyed on the id
    alone would answer south's first cast with north's outcome, which is a
    cross-seat leak reachable without either player doing anything unusual.
    """
    session = in_battle()

    north = session.cast("north", cast("c1"))
    south = session.cast("south", cast("c1"))

    assert north["outcome"] == "accepted"
    assert south["outcome"] == "accepted"
    assert len(session.round.casts()) == 2
    assert {entry.cast_by for entry in session.round.casts()} == {"north", "south"}


def test_a_refused_cast_never_spends() -> None:
    session = in_battle()
    before = session.round.energy_for("north")
    assert session.cast("north", cast("c1", at=Vec2(9999, 9999)))["reason"] == "outOfBounds"
    assert session.round.energy_for("north") == before


# ------------------------------------------------------------ tick and order --


def test_the_server_assigns_the_tick_and_the_order() -> None:
    """Neither is the client's to name.

    A client that could name its tick could book a cast in advance, which is a
    delayed spell nobody else can see coming; one that could name its order
    could push itself ahead of a cast that arrived first.
    """
    rnd = rich_round()
    for _ in range(5):
        rnd.step()

    first = rnd.cast("north", cast("c1", tick=1))
    second = rnd.cast("south", cast("c2", tick=1))

    assert first.accepted and second.accepted
    # Scheduled on the server's own next tick, never on the one the client sent.
    assert first.tick == rnd.world.tick + 1
    assert second.tick == rnd.world.tick + 1
    # And ordered by the sequence the server took them in.
    assert (first.order, second.order) == (1, 2)


def test_order_runs_from_one_with_no_gaps_for_refusals() -> None:
    """A refused cast takes no place in the order — there is nothing to place."""
    rnd = rich_round()
    rnd.step()

    assert rnd.cast("north", cast("a")).order == 1
    assert rnd.cast("north", cast("b", at=Vec2(-1, -1))).order is None
    assert rnd.cast("north", cast("c")).order == 2


def test_accepted_casts_carry_their_order_on_the_wire() -> None:
    rnd = rich_round()
    rnd.step()
    rnd.cast("north", cast("c1"))
    rnd.cast("south", cast("c2"))

    payload = [entry.to_json() for entry in rnd.casts()]
    assert [entry["order"] for entry in payload] == [1, 2]
    assert all(entry["tick"] > 0 for entry in payload)


# ------------------------------------------------------------ stale and phase --


def test_a_cast_from_long_ago_is_refused_as_stale() -> None:
    """A tap that sat in a dead socket must not land where nothing is any more."""
    rnd = rich_round()
    for _ in range(STALE_COMMAND_TICKS + 10):
        rnd.step()

    outcome = rnd.cast("north", cast("old", tick=1))
    assert outcome.accepted is False
    assert outcome.rejection == "stale"


def test_a_cast_from_the_future_is_refused_too() -> None:
    """A client cannot know a tick the server has not run.

    So a `tick` ahead of the world is either a clock that has run away or a
    client trying to book a cast in advance, and the window bounds both
    directions for that reason.
    """
    rnd = rich_round()
    rnd.step()

    outcome = rnd.cast("north", cast("ahead", tick=rnd.world.tick + STALE_COMMAND_TICKS + 1))
    assert outcome.rejection == "stale"


def test_a_recent_cast_is_inside_the_window() -> None:
    rnd = rich_round()
    for _ in range(STALE_COMMAND_TICKS + 10):
        rnd.step()

    assert rnd.cast("north", cast("recent", tick=rnd.world.tick - 1)).accepted is True


def test_a_cast_with_no_tick_is_not_stale() -> None:
    """Zero is what the parser fills in when the client sent nothing.

    Read as "unstated" rather than as tick zero. The window is a courtesy to a
    client that reports where it was looking; a client that reports nothing gets
    no courtesy and no refusal, and the ledger — not this — is what keeps it
    from double-casting.
    """
    rnd = rich_round()
    for _ in range(STALE_COMMAND_TICKS + 10):
        rnd.step()

    assert rnd.cast("north", cast("silent", tick=0)).accepted is True


def test_a_cast_during_planning_is_a_wrong_phase_and_not_a_finished_round() -> None:
    session = make_session()
    outcome = session.cast("north", cast("c1"))
    assert outcome["reason"] == "wrongPhase"


def test_a_cast_after_the_match_is_over_is_a_finished_round() -> None:
    session = in_battle()
    while not session.over:
        session.tick()

    assert session.cast("north", cast("late"))["reason"] == "roundOver"


def test_a_cast_that_arrives_on_the_tick_the_round_ends_is_refused_not_applied() -> None:
    rnd = rich_round(seconds=2)
    while not rnd.over:
        rnd.step()

    outcome = rnd.cast("north", cast("last"))
    assert outcome.rejection == "roundOver"
    assert rnd.casts() == []


# ----------------------------------------------------------------- the ledger --


def test_an_overlong_command_id_is_refused_at_the_parser() -> None:
    """The id becomes a key in a dictionary a client fills in.

    A correlation id is a UUID's worth of characters; anything longer is not a
    client labelling its own casts, and letting it through would mean a socket
    could spend a match's memory budget on one message.
    """
    raw = {
        "commandId": "x" * (MAX_COMMAND_ID_LENGTH + 1),
        "spellId": "meteor",
        "at": {"x": 1, "y": 1},
        "tick": 1,
    }
    with pytest.raises(CommandError, match="commandId"):
        parse_cast_command(raw)

    raw["commandId"] = "x" * MAX_COMMAND_ID_LENGTH
    assert parse_cast_command(raw).command_id == "x" * MAX_COMMAND_ID_LENGTH


def test_the_ledger_forgets_the_oldest_ids_rather_than_growing_for_ever() -> None:
    """Bounded because the key is the client's, and so is how many there are.

    Nothing legitimate is lost: what the ledger protects is a resend of a cast
    the client has not heard about, which happens within seconds. A seat that
    has spent hundreds of ids is not waiting on the first of them.
    """
    ledger = CommandLedger(max_entries_per_seat=4)
    for index in range(10):
        ledger.record("north", LedgerEntry(f"c{index}", accepted=True))

    assert ledger.count_for("north") == 4
    assert ledger.find("north", "c0") is None, "the oldest went first"
    assert ledger.find("north", "c9") is not None


def test_the_ledger_holds_one_entry_per_id_per_seat() -> None:
    session = in_battle()
    for command_id in ("a", "b", "b", "c"):
        session.cast("north", cast(command_id))
    session.cast("south", cast("a"))

    assert session.ledger.count_for("north") == 3
    assert session.ledger.count_for("south") == 1


def test_an_id_spent_in_planning_is_not_reusable_in_the_battle() -> None:
    """A cast refused on the plan screen cannot be resent into the battle.

    A client that could do that would be casting during planning and having it
    take effect a phase later — which is both a rule broken and a spell the
    opponent never saw coming.
    """
    session = make_session()
    refused: dict[str, Any] = session.cast("north", cast("c1"))
    assert refused["reason"] == "wrongPhase"

    plan = fixtures.opening_plan_json(1, MAP)
    session.lock_in("north", plan)
    session.lock_in("south", plan)
    session.tick()

    assert session.cast("north", cast("c1")) == refused
    assert session.round.casts() == []
    # And a fresh id still works, so nothing was poisoned beyond that one.
    assert session.cast("north", cast("c2"))["outcome"] == "accepted"
