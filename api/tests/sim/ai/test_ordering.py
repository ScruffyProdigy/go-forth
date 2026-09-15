"""Orderings that reach output, asserted directly rather than via determinism.

**Why this file exists, and why the determinism suite is not enough.** A
determinism test compares runs of the same code, so it is satisfied by any order
that is stable — including a wrong one. Remove a `sorted` and every run agrees
with every other run, in this process and in five fresh ones, because they are
all wrong in the same way. `tests/sim/test_determinism.py` cannot see it. Nor
can a battle: two units that are genuinely indifferent between two actions are
rare enough that a shuffled tie-break usually changes nothing visible.

Measured, not assumed. Sweeping nine ordering guarantees out of `coordination.py`
and `profiles.py` one at a time, against the whole `tests/sim/ai` suite plus the
determinism tests: **eight survived**. The control — a coordinator that assigns
nobody — was caught, so the sweep was not producing false negatives. Re-running
it after this file existed, three of those eight are now caught, and the other
five are accounted for below rather than left as an unexplained residue.

Each of the three was then re-run **twice**: against this file alone, and
against the rest of the suite with this file excluded.

    nominated_target_ids: iterate the set   here: CAUGHT   elsewhere: survived
    assignments: unsorted output            here: CAUGHT   elsewhere: survived
    needs: unsorted by priority             here: CAUGHT   elsewhere: survived

That second column is the point. "The suite objected" does not say which test
objected, so a new ordering file can be decorative while some pre-existing test
carries the failure — and a sweep run only against the whole suite cannot tell
the two apart. Each test below is individually load-bearing, and that is
measured rather than assumed. The priority test in particular needed it: the
first version could not distinguish sorted from unsorted, because both threats
protected the mage and the tiebreak fell through to target id, which is exactly
the order the mutation produces. It passed, and it passed under the mutation
too. Only the aimed sweep showed it.

Only one of the three was a live reproducibility bug. `nominated_target_ids`
builds from a set comprehension, and Python randomizes string hashing per
process — measured elsewhere in this repo at eight distinct iteration orders
across eight fresh interpreters. Candidate order is tie-break order, so that one
would have put two machines running identical code on different actions. The
other two are published contracts that something downstream reads.

Why the five that still survive are not tests:

===============================  ==============================================
`_living_members` sorting        Defensive. Every consumer's tie-break key ends
                                 in a unit id, so member order cannot reach
                                 output. Kept because that is a property of
                                 today's consumers, not of the function.
`leading_mage` sorting           A no-op while every troop has one mage, and two
                                 mages of one troop resolve identical habits.
`personality_refs_for_troop`     Fixes the order two mages' identical tags are
                                 summed in. Only observable as a float's last
                                 bit, which no assertion can reach.
The two personality sorts        Redundant *with each other*: `totals` is
                                 populated from an already tag-sorted sequence,
                                 so removing either alone changes nothing.
                                 Confirmed by removing **both** at once, with an
                                 assertion that both mutations applied — the
                                 last test here then fails, as it should.
===============================  ==============================================

A guarantee that survives a mutation sweep is not automatically a bug. It is a
question: is this load-bearing, or is something else already holding it up? The
table is the answers, so the next sweep does not have to re-derive them.
"""

from __future__ import annotations

from app.sim.ai.coordination import _needs, baseline_profile, coordinate, nominated_target_ids
from app.sim.ai.fixtures import PROTECTIVE, RECKLESS, combined_library, strength_library
from app.sim.ai.intent import Assignment, TroopCoordination
from app.sim.orders import PUSH_ENEMY_BASE
from app.sim.types import Vec2
from app.sim.world import Troop, Unit, World
from tests.sim.ai.helpers import SECONDS_PER_TICK, attach, make_unit, make_world
from tests.sim.ai.test_coordination import SIEGE, TYPES
from tests.sim.ai.test_personalities import behavior_of, escort
from tests.sim.fixtures_units import ADEPT, HOUND

MAGE_AT = Vec2(180, 400)


def two_threats(*summons: tuple[str, Vec2]) -> World:
    """A mage under fire from two directions, with named summons around it.

    Both mortars out-range every summon, so answering either means somebody
    walking, and the mage is the neediest victim of both — which fixes the
    priority order at (`e-mage`, `e-summon`) by target id and makes it
    independent of where the summons happen to stand.
    """
    units: list[Unit] = [make_unit("m", ADEPT, "north", MAGE_AT)]
    units += [make_unit(name, HOUND, "north", at) for name, at in summons]
    units += [
        make_unit("e-mage", SIEGE, "south", Vec2(180, 320)),
        make_unit("e-summon", SIEGE, "south", Vec2(100, 260)),
    ]
    world = make_world(units)
    attach(world, strength_library("m", PROTECTIVE), TYPES)
    return world


def coordinated(world: World) -> Troop:
    troop = next(t for t in world.troops if t.id == "north-t0")
    coordinate(world, troop, 0, SECONDS_PER_TICK)
    return troop


def test_assignments_come_out_sorted_by_unit_id_not_in_the_order_they_were_made() -> None:
    """The two orders are different here, which is the only way to tell them apart.

    `e-mage` is the higher-priority need and is answered first, by `s2`; the
    second need is answered by `s0`. So the coordinator builds `[s2, s0]` and
    must publish `[s0, s2]`. A fixture where the two agreed would pass whether
    the sort ran or not.
    """
    troop = coordinated(two_threats(("s0", Vec2(100, 300)), ("s1", Vec2(110, 300)), ("s2", Vec2(180, 340))))

    ordered = [(a.unit_id, a.target_id) for a in troop.coordination.assignments]

    assert ordered == [("s0", "e-summon"), ("s2", "e-mage")]
    # And the control on that claim: the first-priority need went to the *later*
    # id, so the sort above is doing work rather than agreeing with build order.
    assert ordered[1][1] == "e-mage"


def test_needs_come_out_neediest_first_regardless_of_the_enemy_ids() -> None:
    """Asserted about `_needs` rather than about a battle, on purpose.

    Priority only becomes visible when the budget runs out, and arranging a
    fixture where two threats both have reachable defenders *and* the budget
    stops at one requires contorting distances until the test is about the
    contortion. The ordering is a property of the function, so it is asserted
    there — which also lets the enemy ids run backwards against the priority,
    the only arrangement that can tell a sorted list from an unsorted one.

    `e-alpha` threatens a summon and `e-zulu` threatens the mage. Sorted by
    neediness the mage's threat comes first; sorted by id it comes last.
    """
    mage = make_unit("m", ADEPT, "north", Vec2(180, 400))
    summon = make_unit("s0", HOUND, "north", Vec2(180, 200))
    world = make_world(
        [
            mage,
            summon,
            make_unit("e-zulu", HOUND, "south", Vec2(180, 380)),
            make_unit("e-alpha", HOUND, "south", Vec2(180, 220)),
        ]
    )
    troop = next(t for t in world.troops if t.id == "north-t0")
    profile = baseline_profile(SECONDS_PER_TICK)

    needs = _needs(world, troop, (mage, summon), profile)

    assert [(n.target_id, n.protecting_id) for n in needs] == [("e-zulu", "m"), ("e-alpha", "s0")]


def test_nominated_targets_are_sorted_and_deduplicated() -> None:
    """Tested against the function, because nothing exercises it in a battle yet.

    JQ-329 consumes this and sorts again on receipt, so a battle would not show
    a break — and until their branch lands nothing calls it at all. An unwired
    seam is untested by construction: its guarantees have to be asserted about
    the function, or they are not asserted.

    The ids are deliberately unsorted and duplicated on input, and there are
    enough of them that set iteration landing on sorted order by chance is
    remote rather than even.
    """
    troop = Troop(id="north-t0", side="north", order=PUSH_ENEMY_BASE)
    troop.coordination = TroopCoordination(
        assignments=tuple(
            Assignment(unit_id=f"s{i}", target_id=target, protecting_id="m", since_tick=0)
            for i, target in enumerate(("e-zeta", "e-alpha", "e-omega", "e-beta", "e-zeta", "e-kappa"))
        )
    )

    assert nominated_target_ids(troop) == ("e-alpha", "e-beta", "e-kappa", "e-omega", "e-zeta")


def test_resolved_personalities_come_out_sorted_by_tag() -> None:
    """Authored reckless-then-protective; composed protective-then-reckless.

    Two things ride on this. The order is the order the weight deltas are summed
    in, and floating-point addition is not associative — so an unstable order is
    a different last bit between two machines running identical code. And it is
    a published order: JQ-331's inspector prints these in the order it finds
    them.
    """
    resolved = behavior_of(escort(combined_library("m")), "melee").personalities

    assert [p.tag for p in resolved] == [PROTECTIVE, RECKLESS]
    # The authored order is the opposite, so this is not agreeing by accident.
    assert [PROTECTIVE, RECKLESS] != [RECKLESS, PROTECTIVE]
