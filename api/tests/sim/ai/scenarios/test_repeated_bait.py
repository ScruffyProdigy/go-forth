"""Scenario: repeated bait.

One bait draws a unit out, and that is fine — a unit that never chased anything
would be a worse unit. What must not happen is that baiting *repeatedly* walks it
off the field a leash-length at a time, because each chase is individually
reasonable and nothing sums them.

This is the scenario with least to learn from a single decision and most from a
run. "Bounded pursuit" is a claim about two hundred ticks of being teased, and
there is no tick at which it is visible.

What the run actually shows is that the bound holds with room to spare: the hound
gets 31.5 units from its post against a leash of 96, over two hundred ticks and
two baits. So the assertions are the ones that would catch a *regression* — that
it is baited at all, that it never passes the leash, that the excursions do not
ratchet, and that it comes home — rather than a pinned distance that would break
on every tuning pass.

The bound is read from JQ-329's `PURSUIT_LEASH` rather than written down here.
It is theirs to tune; that a unit stays inside it however often it is baited is
the invariant, and it survives the tuning.
"""

from __future__ import annotations

from app.sim.ai.fixtures import SAMPLE_PROFILES, SAMPLE_TRAITS
from app.sim.ai.intent import PURSUING, PURSUIT_STARTED
from app.sim.ai.profiles import BehaviorLibrary
from app.sim.ai.pursuit import PURSUIT_LEASH
from app.sim.geometry import distance
from app.sim.orders import hold
from app.sim.types import Vec2
from app.sim.world import Unit
from tests.sim.ai.helpers import make_unit
from tests.sim.ai.scenarios.harness import ScenarioRun, play
from tests.sim.fixtures_units import ADEPT, HOUND, RAM, SPRITE

#: Long enough to be baited several times over, which is the whole point.
TICKS = 200
UNIT_TYPES = (ADEPT, HOUND, RAM, SPRITE)
STAGED = tuple(p for p in SAMPLE_PROFILES if p.type_id in {t.id for t in UNIT_TYPES})
LIBRARY = BehaviorLibrary(traits=SAMPLE_TRAITS, profiles=STAGED)

POST = Vec2(80, 284.5)
#: The baits are posted away from the hound, so they lure rather than attack.
#: With both troops holding the same zone they simply walked into the hound and
#: the scenario became a fight; a bait that does not leave is not a bait.
AWAY = Vec2(295, 284.5)
ORDERS = {"north-t0": hold("W"), "south-t0": hold("E")}

#: The hound is given far more hit points than its card. Two sprites killed it on
#: tick 41 of the first version, and a run that ends in the baited unit dying
#: says nothing about pursuit bounds. This is a fixture about being *lured*, so
#: the hound has to outlive the luring.
TOUGH = 400.0


def baited() -> list[Unit]:
    """A hound at its post, and two quicker baits drifting away from it."""
    return [
        make_unit("hound", HOUND, "north", POST, destination=POST, hp=TOUGH),
        make_unit("bait-a", SPRITE, "south", Vec2(POST.x + 45, POST.y), destination=AWAY),
        make_unit("bait-b", SPRITE, "south", Vec2(POST.x + 45, POST.y + 30), destination=AWAY),
    ]


def run() -> ScenarioRun:
    return play(baited(), UNIT_TYPES, LIBRARY, ticks=TICKS, orders=ORDERS)


def excursions(result: ScenarioRun) -> list[float]:
    """How far from its post the hound was willing to go, decision by decision."""
    return [
        distance(record.station, record.chosen.destination or record.station)
        for record in result.by_unit("hound")
    ]


def test_the_hound_is_actually_baited() -> None:
    """The positive control. A unit that never chases cannot be walked off a field.

    Every bound below is satisfied by a hound that stood still for two hundred
    ticks, which would be the larger failure and would read as a pass.
    """
    result = run()
    reasons = [record.reason for record in result.by_unit("hound")]

    assert reasons, "the hound decided nothing"
    assert PURSUIT_STARTED in reasons or PURSUING in reasons, (
        f"the hound never gave chase; it did {sorted(set(reasons))}"
    )


def test_the_hound_survives_to_be_baited_for_the_whole_run() -> None:
    """Otherwise this measures how long it took to die, not how far it was drawn."""
    result = run()

    assert result.alive("hound")
    assert len(result.by_unit("hound")) > TICKS // 2


def test_repeated_baiting_never_walks_the_hound_past_its_leash() -> None:
    """The invariant, at every decision rather than at the end.

    A unit that wandered a long way and came back would satisfy an assertion made
    only on the final position, and wandering is the failure whatever follows it.
    """
    result = run()
    worst = max(excursions(result))

    assert worst <= PURSUIT_LEASH, (
        f"the hound reached {worst:.1f} from its post, past a leash of {PURSUIT_LEASH}"
    )


def test_the_excursions_do_not_ratchet_over_the_run() -> None:
    """The word "repeated" is the whole scenario.

    One bait drawing a unit out is fine. The failure is each chase starting from
    where the last one ended, so that the unit drifts across the map while every
    individual decision stays inside its bound. Compared as thirds of the run:
    the last third must not be further out than the first.
    """
    values = excursions(run())
    third = len(values) // 3

    assert third > 10, "too few decisions to compare thirds of a run"
    assert max(values[-third:]) <= max(values[:third]) + PURSUIT_LEASH / 2, (
        "the hound was further from its post at the end than the beginning; the chases are accumulating"
    )


def test_the_hound_is_still_near_its_post_at_the_end() -> None:
    """And it came home, rather than merely never having gone far in one step."""
    result = run()
    hound = result.unit("hound")

    assert distance(hound.position, hound.destination) <= PURSUIT_LEASH


def test_an_unbaited_hound_in_the_same_fixture_never_gives_chase() -> None:
    """The contrast: the bound is doing the work, not the absence of temptation."""
    calm = [
        make_unit("hound", HOUND, "north", POST, destination=POST, hp=TOUGH),
        make_unit("bait-a", SPRITE, "south", Vec2(POST.x + 600, POST.y + 600), destination=AWAY),
    ]
    reasons = [r.reason for r in play(calm, UNIT_TYPES, LIBRARY, ticks=TICKS, orders=ORDERS).by_unit("hound")]

    assert reasons, "the hound decided nothing, so its reasons prove nothing"
    assert PURSUIT_STARTED not in reasons
