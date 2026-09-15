"""The ordering guarantees, pinned — because determinism tests cannot reach them.

Every one of these was found by a mutation sweep and survived the whole suite.
The reason they survive is worth stating once, because it applies to any project
with both determinism tests and declared orderings:

**A consistently wrong order is still perfectly consistent.** A determinism test
compares runs of the *same code*, so reversing a sort, or dropping one, changes
every run identically and every such test still passes. Determinism tests prove
a build reproduces itself; they say nothing about whether the order it reproduces
is the one anybody intended.

Two of the three are worse than a style point. `observe._nominations` and
`candidates._answerable` both handle sets, and `CONVENTIONS.md` opens with the
reason that matters here: **Python randomizes string hashing per process**, so
iterating a set of unit ids gives a different order in every fresh interpreter.
Measured on six realistic ids: eight distinct orders across eight interpreters.
Dropping either sort makes battles genuinely irreproducible.

They are latent today only because nothing populates `nominated_target_ids` in a
running battle — JQ-330's coordinator is the producer and has not merged. So the
determinism suite cannot exercise the path at all, however many subprocesses it
spawns, and the guarantee would have been broken silently the day the seam was
wired. JQ-330 swept their own side afterwards and found the same sort missing
from `nominated_target_ids(troop)`, a live bug rather than a missing test. That
is the shape to remember: **an unwired seam is untested by construction**, and
its tests have to be written against the function rather than against a battle.

**These three are not equally severe, and a reader should not have to work that
out.** A surviving mutation is a question — is this load-bearing, or is something
else already holding it up — and the answers differ:

=========================  =================================================
Guarantee                  What it is worth
=========================  =================================================
`_nominations` sorts       **Live hazard.** Builds from a set of unit ids, so
                           dropping the sort puts hash order into output and
                           breaks cross-process reproducibility outright.
`_answerable` walks        **Live hazard.** Same: the alternative iterates a
`enemies`                  set, and candidate order is tie-break order.
`observe` sorts enemies    **Defensive.** `world.units` is a deterministic
                           list, so dropping this sort is still reproducible;
                           it moves the guarantee from local to "depends on
                           how `world.py` happens to order units", and it
                           reaches output only through float summation order
                           in `threat.threats_against`. Worth keeping, worth
                           knowing it is a different claim from the two above.
=========================  =================================================

Each was confirmed load-bearing by pointing the mutation at **this file alone**,
not at the suite: a sweep run against everything reports "caught" without saying
which test caught it, so a new ordering test can look effective while the
failure came from somewhere else entirely. All three fail here and nowhere else.
"""

from __future__ import annotations

from app.sim.ai.candidates import _answerable
from app.sim.ai.observe import _nominations, observe
from app.sim.config import DEFAULT_SIM_CONFIG, seconds_per_tick
from app.sim.map import TWO_LANE_MAP
from app.sim.types import Vec2
from tests.sim.ai.helpers import make_unit, make_world
from tests.sim.fixtures_units import HOUND

SECONDS_PER_TICK = seconds_per_tick(DEFAULT_SIM_CONFIG)
HERE = Vec2(180, 300)

#: Deliberately not in sorted order, and not in reverse either, so neither a
#: missing sort nor a reversed one can pass by coincidence.
SCRAMBLED = ("south-t2-u1", "south-t0-u3", "south-t1-u0", "south-t0-u1")


def test_nominations_come_out_sorted_whatever_order_they_arrive_in() -> None:
    """The caller may hand over a set, and a set iterates in hash order.

    Sorting inside `observe` rather than trusting the producer is what makes the
    guarantee local — the coordinator cannot break reproducibility by handing
    over its working collection.
    """
    assert _nominations(SCRAMBLED) == tuple(sorted(SCRAMBLED))
    assert _nominations(set(SCRAMBLED)) == tuple(sorted(SCRAMBLED))
    assert _nominations(reversed(SCRAMBLED)) == tuple(sorted(SCRAMBLED))
    assert _nominations(None) == ()
    # Deduplicated, since two sources may nominate the same enemy.
    assert _nominations([*SCRAMBLED, SCRAMBLED[0]]) == tuple(sorted(SCRAMBLED))


def test_observed_enemies_are_sorted_even_when_the_world_is_not() -> None:
    """`world.units` is deterministic but its order is not this module's to rely on.

    Staged with a unit list whose order differs from id order, so an observation
    that simply passed the world's order through would be visibly wrong.
    """
    unsorted = ["south-c", "south-a", "south-d", "south-b"]
    world = make_world(
        [make_unit("north-x", HOUND, "north", HERE)]
        + [make_unit(name, HOUND, "south", Vec2(HERE.x + 20 + i, HERE.y)) for i, name in enumerate(unsorted)]
    )
    assert [u.id for u in world.units if u.side == "south"] == unsorted, "fixture is not scrambled"

    observation = observe(world, world.units[0], TWO_LANE_MAP, SECONDS_PER_TICK)

    assert [enemy.id for enemy in observation.enemies] == sorted(unsorted)


def test_answerable_walks_the_enemies_not_the_nomination_set() -> None:
    """The set is for membership; the order comes from the sorted enemy list.

    `_answerable` unions nominations, the current chase and the nearest enemy
    into a set, then filters `observation.enemies` by it. Iterating the set
    instead would put hash order into the candidate list — and candidate order is
    tie-break order, so two actions a unit is indifferent between would resolve
    differently in different interpreters.
    """
    hound = make_unit("north-x", HOUND, "north", HERE)
    enemies = ["south-c", "south-a", "south-d", "south-b"]
    world = make_world(
        [hound]
        + [
            make_unit(name, HOUND, "south", Vec2(HERE.x + 20 + i * 3, HERE.y))
            for i, name in enumerate(enemies)
        ]
    )

    observation = observe(
        world, hound, TWO_LANE_MAP, SECONDS_PER_TICK, nominated_target_ids=reversed(enemies)
    )
    answerable = [enemy.id for enemy in _answerable(observation)]

    assert answerable, "nothing was answerable, so the ordering claim is untested"
    assert answerable == sorted(answerable)
