"""Bounded pursuit: when a chase starts, what ends it, and what happens after.

A chase is the only decision in the package that outlives the tick that made it,
so it is the only one whose bounds cannot be expressed as a weight. These pin the
bounds themselves; `test_behaviors.py` pins what they look like in a running
battle.
"""

from __future__ import annotations

from app.sim.ai.decide import decide
from app.sim.ai.intent import (
    PURSUIT_ABANDONED_INVALID,
    PURSUIT_ABANDONED_LEASH,
    PURSUIT_ABANDONED_TIMEOUT,
    PURSUIT_ABANDONED_UNREACHABLE,
    PURSUIT_STARTED,
    TARGET_SWITCHED,
    Commitment,
    UnitAi,
)
from app.sim.ai.observe import Observation, observe
from app.sim.ai.profiles import NEUTRAL_BEHAVIOR
from app.sim.ai.pursuit import (
    PURSUIT_LEASH,
    PURSUIT_PATIENCE_SECONDS,
    PURSUIT_RECOVERY_SECONDS,
    PURSUIT_TIMEOUT_SECONDS,
    eligible_targets,
    release_reason,
)
from app.sim.config import DEFAULT_SIM_CONFIG, to_ticks
from app.sim.geometry import distance
from app.sim.map import TWO_LANE_MAP
from app.sim.types import Vec2
from app.sim.world import Unit, World
from tests.sim.ai.helpers import SECONDS_PER_TICK, make_unit, make_world
from tests.sim.fixtures_units import HOUND, RAM, SPRITE

HERE = Vec2(180, 300)
TICKS = DEFAULT_SIM_CONFIG.tick_rate

#: A station out beyond the quarry, so that closing on it is objective progress
#: as well as a chase. `helpers.make_unit` defaults a unit's station to its own
#: feet, which is the right neutral setting for a scoring test and the wrong one
#: here: every advance then scores a full stride of lost ground and `hold` wins
#: whatever the chase is worth. A test about *which* target a unit commits to
#: has to be staged where committing to one is what it would do.
DOWNFIELD = Vec2(HERE.x + 400, HERE.y)

#: An opening gap far wider than the staged one, so the progress bound is
#: satisfied and a test about the timeout is about the timeout. `release_reason`
#: reports the most basic broken bound first, and a hand-placed world where
#: nobody actually moves fails the progress bound on every tick.
WIDE_OPENING = 400.0


def with_ai(unit: Unit) -> UnitAi:
    """`make_unit` leaves `ai` unset; composing behaviour is `attach`'s job.

    These tests are about commitment state rather than about weights, so they
    attach a neutral one directly instead of building a library to get at it.
    """
    if unit.ai is None:
        unit.ai = UnitAi()
    return unit.ai


def chasing(world: World, hunter: Unit, target_id: str, started: int = 0, gap: float | None = None) -> None:
    """Puts a chase already in progress onto the hunter."""
    quarry = next(u for u in world.units if u.id == target_id)
    with_ai(hunter).commitment = Commitment(
        target_id=target_id,
        started_tick=started,
        origin=hunter.position,
        opening_gap=distance(hunter.position, quarry.position) if gap is None else gap,
    )


def look_at(world: World, unit: Unit, tick: int = 0) -> Observation:
    world.tick = tick
    return observe(world, unit, TWO_LANE_MAP, SECONDS_PER_TICK)


def test_a_chase_is_committed_to_and_then_continued_rather_than_rebuilt() -> None:
    """The commitment has to persist or none of its bounds mean anything.

    A timeout measured from a start tick that is rewritten every tick never
    expires; a leash anchored wherever the unit currently stands is not a leash.
    """
    hunter = make_unit("h", HOUND, "north", HERE, destination=DOWNFIELD)
    world = make_world([hunter, make_unit("q", RAM, "south", Vec2(HERE.x + 60, HERE.y))])
    with_ai(hunter)

    first = decide(look_at(world, hunter), NEUTRAL_BEHAVIOR)

    assert first.commitment is not None
    assert first.commitment.target_id == "q"
    assert first.reason == PURSUIT_STARTED
    assert first.commitment.opening_gap == distance(HERE, Vec2(HERE.x + 60, HERE.y))


def test_a_chase_that_is_not_closing_the_gap_is_abandoned_as_unreachable() -> None:
    """Measured, not compared.

    There is deliberately no "am I faster than it" test — two units of identical
    speed walking at each other close perfectly well, and gating on speed stopped
    a cinder-hound ever advancing on another cinder-hound. What matters is
    whether the gap is shutting, and a chase that has not shut any of it after a
    second is not working whatever the reason: faster quarry, circling quarry, or
    one being led away on purpose.
    """
    hunter = make_unit("h", HOUND, "north", HERE)
    world = make_world([hunter, make_unit("q", SPRITE, "south", Vec2(HERE.x + 60, HERE.y))])
    chasing(world, hunter, "q", started=0, gap=60.0)

    patient = look_at(world, hunter, tick=int(PURSUIT_PATIENCE_SECONDS * TICKS) - 1)
    assert release_reason(patient) is None, "given a moment to show it is working"

    out_of_patience = look_at(world, hunter, tick=int(PURSUIT_PATIENCE_SECONDS * TICKS) + 1)
    assert release_reason(out_of_patience) == PURSUIT_ABANDONED_UNREACHABLE


def test_a_chase_that_is_closing_the_gap_is_left_alone() -> None:
    """The complement, without which the test above is satisfied by never chasing."""
    hunter = make_unit("h", HOUND, "north", HERE)
    world = make_world([hunter, make_unit("q", RAM, "south", Vec2(HERE.x + 40, HERE.y))])
    chasing(world, hunter, "q", started=0, gap=100.0)

    assert release_reason(look_at(world, hunter, tick=int(PURSUIT_PATIENCE_SECONDS * TICKS) + 1)) is None


def test_a_chase_ends_when_the_unit_has_roamed_past_the_leash() -> None:
    """The leash bounds how far the *unit* has gone, not how far off the quarry is.

    Those differ by the unit's whole reach. Measuring the quarry instead forbids
    a long-ranged unit from taking one step toward something it could then shoot,
    which is a refusal to engage wearing a bound on pursuit.
    """
    hunter = make_unit("h", HOUND, "north", Vec2(HERE.x + PURSUIT_LEASH + 10, HERE.y))
    world = make_world([hunter, make_unit("q", RAM, "south", Vec2(HERE.x + PURSUIT_LEASH + 200, HERE.y))])
    with_ai(hunter).commitment = Commitment(
        target_id="q", started_tick=0, origin=HERE, opening_gap=WIDE_OPENING
    )

    assert release_reason(look_at(world, hunter, tick=2)) == PURSUIT_ABANDONED_LEASH


def test_a_chase_ends_on_its_timeout_even_while_it_is_still_gaining() -> None:
    """A chase that closes slowly enough would otherwise pass the progress test for ever."""
    hunter = make_unit("h", HOUND, "north", HERE)
    world = make_world([hunter, make_unit("q", RAM, "south", Vec2(HERE.x + 30, HERE.y))])
    chasing(world, hunter, "q", started=0, gap=WIDE_OPENING)

    assert release_reason(look_at(world, hunter, tick=2)) is None
    assert (
        release_reason(look_at(world, hunter, tick=int(PURSUIT_TIMEOUT_SECONDS * TICKS) + 1))
        == PURSUIT_ABANDONED_TIMEOUT
    )


def test_a_chase_ends_promptly_when_its_quarry_dies() -> None:
    """Dead, and therefore filtered out of `enemies` before this is asked."""
    hunter = make_unit("h", HOUND, "north", HERE)
    world = make_world([hunter, make_unit("q", RAM, "south", Vec2(HERE.x + 30, HERE.y), hp=0)])
    chasing(world, hunter, "q")

    assert release_reason(look_at(world, hunter, tick=1)) == PURSUIT_ABANDONED_INVALID


def test_after_a_chase_ends_the_unit_cannot_immediately_start_another() -> None:
    """Repeated bait is exactly this, and recovery is the only thing that answers it.

    Without it a chase ends on its timeout and is re-committed on the very next
    tick — the same endless chase with extra bookkeeping — and a single enemy
    stepping in and out of range walks a guard off the field one leash at a time.
    """
    hunter = make_unit("h", HOUND, "north", HERE, destination=DOWNFIELD)
    world = make_world([hunter, make_unit("q", RAM, "south", Vec2(HERE.x + 30, HERE.y))])
    chasing(world, hunter, "q", started=0, gap=WIDE_OPENING)

    ended = decide(look_at(world, hunter, tick=int(PURSUIT_TIMEOUT_SECONDS * TICKS) + 1), NEUTRAL_BEHAVIOR)

    assert ended.reason == PURSUIT_ABANDONED_TIMEOUT
    assert ended.commitment is None
    assert ended.recovery_remaining == to_ticks(PURSUIT_RECOVERY_SECONDS, DEFAULT_SIM_CONFIG)

    # And while recovering, nothing it would have to travel to is on offer.
    ai = with_ai(hunter)
    ai.commitment = None
    ai.recovery_remaining = ended.recovery_remaining
    assert eligible_targets(look_at(world, hunter, tick=100)) == ()


def test_recovery_still_lets_a_unit_fight_what_is_standing_in_front_of_it() -> None:
    """Recovery bars being drawn off, not defending itself.

    A guard that has just been baited is not stunned; what it declines is a
    second trip, and something already inside its weapon costs it no trip at all.
    """
    hunter = make_unit("h", HOUND, "north", HERE)
    world = make_world([hunter, make_unit("q", RAM, "south", Vec2(HERE.x + HOUND.range / 2, HERE.y))])
    with_ai(hunter).recovery_remaining = 40

    assert eligible_targets(look_at(world, hunter, tick=5)) == ("q",)


def test_switching_targets_needs_a_real_improvement_not_a_rounding_error() -> None:
    """Two near-identical quarries otherwise make a unit dither between them.

    Flipping every time they jostle looks like indecision and is worse than
    either choice, because the unit closes on neither. The exemption is the one
    the ticket names: if the committed action has become invalid there is nothing
    to hold on to, and the margin is not applied.
    """
    hunter = make_unit("h", HOUND, "north", HERE, destination=DOWNFIELD)
    committed = make_unit("a", RAM, "south", Vec2(HERE.x + 41, HERE.y))
    # A hair closer and a hair more wounded: worth 0.0002 more, measured.
    barely_better = make_unit("b", RAM, "south", Vec2(HERE.x + 40, HERE.y), hp=RAM.max_hp - 2)
    world = make_world([hunter, committed, barely_better])
    chasing(world, hunter, "a", gap=WIDE_OPENING)

    held = decide(look_at(world, hunter, tick=2), NEUTRAL_BEHAVIOR)
    assert held.selected.target_id == "a", "a rounding error is not a reason to change your mind"

    # Now make the alternative genuinely better: it has closed, and one swing
    # would finish it. Both halves of "meaningful" at once, deliberately — a
    # margin that only just clears is a test that starts failing the next time
    # anybody tunes a scoring constant, and these numbers are provisional by
    # the ticket's own terms.
    barely_better.position = Vec2(HERE.x + 25, HERE.y)
    barely_better.hp = 1
    switched = decide(look_at(world, hunter, tick=2), NEUTRAL_BEHAVIOR)
    assert switched.selected.target_id == "b"
    assert switched.reason == TARGET_SWITCHED
    assert switched.commitment is not None and switched.commitment.target_id == "b"
