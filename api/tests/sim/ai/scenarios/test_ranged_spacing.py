"""Scenario: ranged spacing.

JQ-329 owns the behaviour and pins it on one decision in
`tests/sim/ai/test_behaviors.py`. This owns the **run**, and the two do not
agree — which is the reason this package exists.

Their test stages an adept thirty units from a ram and asserts the gap has grown
by the end. Played through the real phase pipeline for sixty ticks, with the
orders phase rewriting stations underneath, it has not: the adept ends 2.4 units
from the ram and the sprite 17.0, both inside its reach of 18. Range maintenance
fires — 14 of the sprite's 60 decisions — and then loses to engaging.

So this asserts what is true rather than what the unit test hopes. Range
management is a real, named, inspectable decision; a ranged unit hurts a melee
unit before contact; and one with more reach keeps more distance than one with
less. **That the spacing does not survive a whole battle is written up as a
finding in `docs/ai-decision-cost.md` rather than asserted away here.**

Failing until the behaviour matched would be right if this were a bug in
JQ-329's code. It is not — their assertion holds on their fixture. The
divergence is what sixty ticks do to a one-decision claim, which is the thing no
unit test can see.
"""

from __future__ import annotations

from app.sim.ai.fixtures import SAMPLE_PROFILES, SAMPLE_TRAITS
from app.sim.ai.intent import MAINTAINING_RANGE, RETREATING, WITHDRAWING
from app.sim.ai.profiles import BehaviorLibrary
from app.sim.geometry import distance
from app.sim.orders import hold
from app.sim.types import Vec2
from app.sim.units import UnitType
from app.sim.world import Unit
from tests.sim.ai.helpers import make_unit
from tests.sim.ai.scenarios.harness import ScenarioRun, play
from tests.sim.fixtures_units import ADEPT, HOUND, RAM, SPRITE

TICKS = 60
UNIT_TYPES = (ADEPT, HOUND, RAM, SPRITE)
STAGED = tuple(p for p in SAMPLE_PROFILES if p.type_id in {t.id for t in UNIT_TYPES})
LIBRARY = BehaviorLibrary(traits=SAMPLE_TRAITS, profiles=STAGED)

#: Reasons that mean the unit is managing distance rather than merely moving.
SPACING = (MAINTAINING_RANGE, WITHDRAWING, RETREATING)

#: Both troops hold, and the ranged unit starts **on its own station**. Both
#: halves are load-bearing and each was learned by getting it wrong.
#:
#: Under the default push order the orders phase rewrites every station toward
#: the enemy base each tick, so the two units walked to opposite ends of the map
#: and never met — the gap grew to 210 and every spacing assertion passed for the
#: worst possible reason.
#:
#: Then, holding but posted away from the enemy, the spacing came free: walking
#: to post happened to point away from the ram, and the trace honestly said
#: `pressing_objective`. Standing on the station is what makes keeping distance
#: cost something rather than fall out of the walk.
HOLDING = {"north-t0": hold("W"), "south-t0": hold("W")}
POST = Vec2(80, 284.5)
OPENING = 30.0


def skirmish(ranged: UnitType) -> list[Unit]:
    """A ranged unit at its post, and a slow melee unit walking at it."""
    return [
        make_unit("ranged", ranged, "north", POST, destination=POST),
        make_unit("chaser", RAM, "south", Vec2(POST.x, POST.y + OPENING), destination=POST),
    ]


def run(ranged: UnitType = SPRITE) -> ScenarioRun:
    return play(skirmish(ranged), UNIT_TYPES, LIBRARY, ticks=TICKS, orders=HOLDING)


def final_gap(result: ScenarioRun) -> float:
    return distance(result.unit("ranged").position, result.unit("chaser").position)


def test_the_chaser_actually_closes() -> None:
    """The positive control, and it earned itself twice.

    Both earlier stagings left the ram never reaching the ranged unit at all,
    and every spacing assertion passed because nothing was being kept at bay.
    This is the assertion that failed and said so, both times.
    """
    result = run()

    assert result.by_unit("chaser"), "the chaser never decided anything"
    assert final_gap(result) < OPENING, "the ram never closed, so nothing was kept at range"


def test_range_management_is_a_named_decision_in_the_trace() -> None:
    """The inspector's half: a reader should not infer intent from coordinates."""
    result = run()
    reasons = [record.reason for record in result.by_unit("ranged")]

    assert reasons, "the ranged unit decided nothing"
    assert set(reasons) & set(SPACING), f"it never managed range; it did {sorted(set(reasons))}"


def test_the_ranged_unit_hurts_the_melee_unit_before_contact() -> None:
    """Spacing that never fires is flight. Shooting is what makes it skirmishing."""
    result = run()

    assert result.unit("chaser").hp < RAM.max_hp, "it kept its distance without ever shooting"


def test_more_reach_buys_more_distance() -> None:
    """Behaviour read off live stats rather than attached to a creature id.

    A comparison because both absolute distances are currently poor — see the
    module docstring. That the sprite ends further out than the adept is the
    part that should survive retuning.
    """
    assert final_gap(run(SPRITE)) > final_gap(run(ADEPT))


def test_a_unit_with_no_reach_advantage_never_manages_range() -> None:
    """The contrast that makes this a claim about reach rather than about units.

    Deliberately a ram against a ram. The obvious contrast was a `cinder-hound`,
    on the assumption that a melee creature does not skirmish — and it does: a
    hound reaches 20 against the ram's 18, and spends 13 of its decisions
    keeping that two-unit edge. That is JQ-329's rule working exactly as written,
    read off live reach rather than off a creature id, and my assumption about
    what "melee" means was the thing that was wrong.

    Identical reach leaves nothing to keep, and the behaviour disappears.
    """
    reasons = [record.reason for record in run(RAM).by_unit("ranged")]
    hound_reasons = [record.reason for record in run(HOUND).by_unit("ranged")]

    assert reasons, "the unit decided nothing, so its reasons prove nothing"
    assert MAINTAINING_RANGE not in reasons
    # The positive half: the same fixture with a two-unit edge does manage range,
    # so the absence above is about the edge and not about the staging.
    assert MAINTAINING_RANGE in hound_reasons
