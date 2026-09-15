"""Scenario: personality comparison with an identical entourage.

The ticket is specific that the comparison has to hold everything else still —
"comparisons preserve identical stats/entourage where isolating personality
effects". So both runs stage the same creatures, in the same places, under the
same order, on the same seed. The only difference between them is the tag on the
mage leading the troop.

What is asserted is that the two runs **diverge**, and that the trace **says
which tag did it** — not that a reckless hound scores 0.51. The numbers are
provisional tuning data by the ticket's own description; the invariant is that
personality reaches the decision at all, and is visible in the explanation when
it does.
"""

from __future__ import annotations

from app.sim.ai.fixtures import (
    GUARDIAN,
    METHODICAL,
    RECKLESS,
    SAMPLE_PERSONALITIES,
    SAMPLE_PROFILES,
    SAMPLE_TRAITS,
)
from app.sim.ai.profiles import MAX_STRENGTH, BehaviorLibrary, MagePersonality, PersonalityRef
from app.sim.types import Vec2
from app.sim.world import Unit
from tests.sim.ai.helpers import make_unit
from tests.sim.ai.scenarios.harness import ScenarioRun, play, tags, weight
from tests.sim.fixtures_units import ADEPT, HOUND

TICKS = 20
UNIT_TYPES = (ADEPT, HOUND)


#: The entourage, identical in every run below: one mage, two hounds, and an
#: enemy standing off to one side so that "press it" and "hold the line" are
#: genuinely different choices rather than the same walk.
def entourage() -> list[Unit]:
    return [
        make_unit("mage", ADEPT, "north", Vec2(100, 100), destination=Vec2(100, 140)),
        make_unit("hound-a", HOUND, "north", Vec2(90, 110), destination=Vec2(90, 150)),
        make_unit("hound-b", HOUND, "north", Vec2(110, 110), destination=Vec2(110, 150)),
        make_unit("bait", HOUND, "south", Vec2(180, 130)),
        make_unit("enemy-mage", ADEPT, "south", Vec2(200, 200)),
    ]


#: The sample library profiles four creature types; this scenario stages two of
#: them, and `index_library` rejects a profile naming a type the battle does not
#: field. Filtering here rather than trimming the fixture keeps the shared
#: fixture shared.
STAGED = tuple(profile for profile in SAMPLE_PROFILES if profile.type_id in {t.id for t in UNIT_TYPES})


def library(*refs: PersonalityRef) -> BehaviorLibrary:
    return BehaviorLibrary(
        traits=SAMPLE_TRAITS,
        personalities=SAMPLE_PERSONALITIES,
        profiles=STAGED,
        mage_personalities=(MagePersonality(unit_id="mage", personalities=refs),),
    )


def run_with(*refs: PersonalityRef) -> ScenarioRun:
    return play(entourage(), UNIT_TYPES, library(*refs), ticks=TICKS)


def opening(run: ScenarioRun) -> list[tuple[str, str, float, float, float]]:
    """Each unit's identity, stats and starting place, as the run received them."""
    return sorted((unit.id, unit.type_id, unit.max_hp, unit.damage, unit.speed) for unit in run.world.units)


def test_the_entourage_is_genuinely_identical_between_runs() -> None:
    """Guards every comparison below: if the fixtures differed, divergence proves nothing.

    Deliberately not a `entourage() == entourage()` check, which would only test
    the fixture builder. This compares what the two *runs* were actually given.
    """
    reckless = run_with(PersonalityRef(RECKLESS))
    methodical = run_with(PersonalityRef(METHODICAL))

    assert opening(reckless) == opening(methodical)
    assert [r.type_id for r in reckless.by_unit("hound-a")] == [
        r.type_id for r in methodical.by_unit("hound-a")
    ]
    # And the same troop structure, so "same entourage" covers who leads whom.
    assert sorted(t.id for t in reckless.world.troops) == sorted(t.id for t in methodical.world.troops)


def test_a_reckless_troop_and_a_methodical_one_do_not_behave_the_same() -> None:
    reckless = run_with(PersonalityRef(RECKLESS))
    methodical = run_with(PersonalityRef(METHODICAL))

    diverged = (
        reckless.actions("hound-a") != methodical.actions("hound-a")
        or reckless.targets("hound-a") != methodical.targets("hound-a")
        or reckless.unit("hound-a").position != methodical.unit("hound-a").position
    )

    assert diverged, "personality did not reach the decision at all"


def test_a_reckless_troop_discounts_danger_relative_to_a_methodical_one() -> None:
    """The direction is the invariant; the magnitude is provisional tuning data."""
    reckless = run_with(PersonalityRef(RECKLESS)).by_unit("hound-a")[0]
    methodical = run_with(PersonalityRef(METHODICAL)).by_unit("hound-a")[0]

    assert weight(reckless, "danger") < weight(methodical, "danger")


def test_the_trace_names_the_personality_that_was_in_play() -> None:
    run = run_with(PersonalityRef(RECKLESS))

    assert RECKLESS in tags(run.by_unit("hound-a")[0])
    assert METHODICAL not in tags(run.by_unit("hound-a")[0])


def test_the_mages_personality_reaches_its_summons_not_just_itself() -> None:
    """A personality lives on the mage and is meant to lead the whole troop.

    Uses `GUARDIAN`, which JQ-330 is replacing with `PROTECTIVE`. The tag is
    incidental here — any personality would do — so the integration pass swaps
    the name and nothing else. Flagged because it is the one place in this
    package that names a tag JQ-330 removes rather than renames in place.
    """
    run = run_with(PersonalityRef(GUARDIAN))

    for unit_id in ("mage", "hound-a", "hound-b"):
        assert GUARDIAN in tags(run.by_unit(unit_id)[0])


def test_it_does_not_reach_the_other_side() -> None:
    run = run_with(PersonalityRef(RECKLESS))

    assert tags(run.by_unit("bait")[0]) == ()


def test_a_raised_strength_moves_the_weight_further_than_the_default() -> None:
    """Asserted on the mage, which has room to move. See the saturation test below.

    The hound cannot answer this question: `cinder-hound` opens at danger 0.75,
    `aggressive` takes 0.5 off it and one reckless mage takes the remaining 0.25
    and more, so it is already clamped at the floor before strength is raised.
    """
    default = run_with(PersonalityRef(RECKLESS)).by_unit("mage")[0]
    raised = run_with(PersonalityRef(RECKLESS, strength=2.0)).by_unit("mage")[0]

    assert weight(raised, "danger") < weight(default, "danger")


def test_strength_saturates_at_the_weight_floor_rather_than_going_negative() -> None:
    """A creature already at zero danger cannot be made to seek harm.

    `factors.py` is explicit that weights stay non-negative so "ignores danger"
    is a small weight and never a sign flip. This is that rule observed from the
    outside: the aggressive hound bottoms out and stays there however reckless
    its mage gets — which is also why the test above asks the mage instead.
    """
    hound_at_default = run_with(PersonalityRef(RECKLESS)).by_unit("hound-a")[0]
    hound_at_max = run_with(PersonalityRef(RECKLESS, strength=MAX_STRENGTH)).by_unit("hound-a")[0]

    assert weight(hound_at_default, "danger") == 0.0
    assert weight(hound_at_max, "danger") == 0.0


def test_a_zero_strength_contributes_nothing_rather_than_inverting() -> None:
    """The ticket is explicit: zero means no preference, not the opposite one."""
    zero = run_with(PersonalityRef(RECKLESS, strength=0.0)).by_unit("hound-a")[0]
    without = play(entourage(), UNIT_TYPES, library(), ticks=TICKS).by_unit("hound-a")[0]

    assert weight(zero, "danger") == weight(without, "danger")
    assert weight(zero, "target_suitability") == weight(without, "target_suitability")
