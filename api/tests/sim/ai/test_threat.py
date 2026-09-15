"""Danger, and the closing term that made it mean anything.

The measurement JQ-329 was written against: on the delivered JQ-328 evaluator a
unit forty map units from something walking at it scored `danger = 0.00` on every
candidate, because only enemies already within their own weapon range counted.
Every test here exists to stop that coming back in one form or another.
"""

from __future__ import annotations

import pytest

from app.sim.ai.candidates import Candidate
from app.sim.ai.factors import NEUTRAL_WEIGHTS
from app.sim.ai.scoring import score_candidate
from app.sim.ai.threat import EDGE_EXPOSURE, threat_from, threats_against
from app.sim.geometry import distance
from app.sim.types import Vec2
from app.sim.world import Unit, World
from tests.sim.ai.helpers import SECONDS_PER_TICK, look, make_unit, make_world
from tests.sim.fixtures_units import ADEPT, HOUND, RAM, SPRITE

HERE = Vec2(180, 300)


def danger_of(world: World, unit: Unit, candidate: Candidate) -> float:
    """The raw danger verdict, which is what these tests are about.

    Weights scale a factor; they do not compute one. Neutral weights keep the
    raw value on show rather than mixed into a total with three other things.
    """
    scored = score_candidate(look(world, unit), candidate, NEUTRAL_WEIGHTS)
    return next(c.raw for c in scored.contributions if c.factor == "danger")


def test_something_walking_at_you_is_dangerous_before_it_arrives() -> None:
    """The regression the whole ticket turns on.

    A melee enemy forty units off cannot swing yet. Under JQ-328 that made it
    worth exactly nothing, so a wary profile and a reckless one weighed an
    identical board and the defining trait of the `wary` ember-adept multiplied
    zero. It is worth something now, and the something is bounded by what a
    threat clipping your edge is worth.
    """
    adept = make_unit("a", ADEPT, "north", HERE)
    world = make_world([adept, make_unit("r", RAM, "south", Vec2(HERE.x + 40, HERE.y))])

    danger = danger_of(world, adept, Candidate(kind="hold", destination=HERE))

    assert danger < 0.0


def test_a_threat_exactly_at_its_own_reach_scores_the_same_from_either_side() -> None:
    """`CONVENTIONS.md`: predicates must overlap on an interval, not at a point.

    Two branches decide this number — one for enemies in reach, one for enemies
    still closing — and they meet where the gap equals the enemy's reach. If they
    disagreed there, danger would step discontinuously at a distance floating
    point cannot reliably land on, which is the shape of the two bugs that file
    records. They agree because depth is zero on one side and imminence is one on
    the other, and both land on `EDGE_EXPOSURE`.
    """
    enemy = make_unit("e", RAM, "south", Vec2(HERE.x + RAM.range, HERE.y))

    on_the_line = threat_from(enemy, HERE, HERE, SECONDS_PER_TICK)

    assert on_the_line.incoming == pytest.approx(RAM.damage * EDGE_EXPOSURE)
    assert on_the_line.imminence == pytest.approx(1.0)


def test_a_threat_you_are_outrunning_stops_counting_and_one_you_are_not_does_not() -> None:
    """The ticket's criterion, in its own terms.

    "Whether backing off is viable should fall out of the speed differential —
    the ember-sprite can hold off an ash-ram and not a cinder-hound — rather than
    from a stance flag."

    Neither creature is labelled. The sprite is quicker than the ram and slower
    than the hound, and that is the entire input.
    """
    sprite = make_unit("s", SPRITE, "north", HERE)
    leaving = Vec2(HERE.x - sprite.speed * SECONDS_PER_TICK, HERE.y)

    ram = make_unit("r", RAM, "south", Vec2(HERE.x + 40, HERE.y))
    hound = make_unit("h", HOUND, "south", Vec2(HERE.x + 40, HERE.y))

    assert ram.speed < sprite.speed < hound.speed

    outrun = threats_against((ram,), HERE, leaving, SECONDS_PER_TICK)[0]
    outpaced = threats_against((hound,), HERE, leaving, SECONDS_PER_TICK)[0]

    assert outrun.incoming == 0.0, "an enemy that can never reach you is not a threat"
    assert outpaced.incoming > 0.0, "an enemy faster than you is still coming"


def test_walking_away_from_something_already_in_reach_does_not_shed_it() -> None:
    """JQ-328's rule, kept, because the failure behind it was severe.

    Scoring a move at its destination alone made leaving strictly safer than
    standing, and two armies strolled through each other and out the far side:
    everybody disengaged the moment they were hit, nobody could re-engage, and a
    battle that ended in eighteen seconds without a decision loop ran the full
    ninety with one.

    JQ-329 narrows the rule to the enemies it was actually about — the ones
    already swinging — instead of applying it to everybody, which is what made
    every form of giving ground score exactly what holding scored.
    """
    hound = make_unit("h", HOUND, "north", HERE)
    contact = make_unit("e", HOUND, "south", Vec2(HERE.x + 5, HERE.y))
    world = make_world([hound, contact])

    standing = danger_of(world, hound, Candidate(kind="hold", destination=HERE))
    leaving = danger_of(world, hound, Candidate(kind="retreat", destination=Vec2(HERE.x - 200, HERE.y)))

    assert leaving == pytest.approx(standing), "a swing already landing cannot be outrun this tick"


def test_giving_ground_is_safer_than_standing_when_the_threat_is_still_arriving() -> None:
    """And the complementary half, which is the one that was missing.

    Pinned together with the test above on purpose. "Never safer" is satisfied
    perfectly by a rule that makes leaving pointless, and that was the bug —
    `min(standing, arriving)` is always the standing figure, so every withdraw
    scored exactly what its hold scored. `CONVENTIONS.md` makes the general point:
    an invariant of the form "never better than X" needs its complement written
    beside it or it is not evidence of anything.
    """
    sprite = make_unit("s", SPRITE, "north", HERE)
    world = make_world([sprite, make_unit("r", RAM, "south", Vec2(HERE.x + 40, HERE.y))])

    standing = danger_of(world, sprite, Candidate(kind="hold", destination=HERE))
    leaving = danger_of(world, sprite, Candidate(kind="retreat", destination=Vec2(HERE.x - 200, HERE.y)))

    assert leaving > standing


def test_advancing_on_one_enemy_counts_the_one_it_turns_its_back_on() -> None:
    """Closing rate is read off the two positions, so this needs no special case.

    A candidate that closes on the enemy in front opens the gap to the enemy
    behind, and the bearing-free formulation says so without anyone reasoning
    about angles — which is the reason it is written that way.
    """
    ahead = make_unit("f", RAM, "south", Vec2(HERE.x + 60, HERE.y))
    behind = make_unit("b", RAM, "south", Vec2(HERE.x - 60, HERE.y))

    toward = Vec2(HERE.x + 2, HERE.y)
    closing, opening = threats_against((ahead, behind), HERE, toward, SECONDS_PER_TICK)

    assert distance(toward, ahead.position) < distance(HERE, ahead.position)
    assert closing.incoming > opening.incoming
