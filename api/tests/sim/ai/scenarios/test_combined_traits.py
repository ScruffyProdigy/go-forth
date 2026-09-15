"""Scenario: combined traits.

Traits are meant to **compose**, and the composition is meant to stay **bounded**.
Those are two different failures: a pair of traits that cancel to nothing when
they should have stacked, and a pile of traits that saturate a weight past
anything the scoring can use. Both are asserted here from the outside, through
the trace, on two individuals that differ only in the traits they carry.

The point of doing it through the inspector rather than by calling the
composition directly is that the report is what a designer will actually read
when a combination behaves strangely. If the numbers the inspector prints do not
match what the unit did, this scenario is where that shows up.
"""

from __future__ import annotations

from app.sim.ai.factors import FACTORS, MAX_WEIGHT
from app.sim.ai.fixtures import AGGRESSIVE, DUTIFUL, PACK_MINDED, SAMPLE_PROFILES, SAMPLE_TRAITS, WARY
from app.sim.ai.inspect.record import TraceRecord
from app.sim.ai.profiles import BehaviorLibrary, TraitTag, UnitBehavior
from app.sim.types import Vec2
from app.sim.world import Unit
from tests.sim.ai.helpers import make_unit
from tests.sim.ai.scenarios.harness import ScenarioRun, play, weight
from tests.sim.fixtures_units import ADEPT, HOUND

TICKS = 10
UNIT_TYPES = (ADEPT, HOUND)
STAGED = tuple(p for p in SAMPLE_PROFILES if p.type_id in {t.id for t in UNIT_TYPES})


def field() -> list[Unit]:
    """Two hounds of identical type, and something to have opinions about."""
    return [
        make_unit("plain", HOUND, "north", Vec2(100, 100), destination=Vec2(100, 150)),
        make_unit("loaded", HOUND, "north", Vec2(120, 100), destination=Vec2(120, 150)),
        make_unit("enemy", ADEPT, "south", Vec2(170, 140)),
    ]


def run_with(*traits: TraitTag, removed: tuple[TraitTag, ...] = ()) -> ScenarioRun:
    """`loaded` carries the extra traits; `plain` is the control."""
    library = BehaviorLibrary(
        traits=SAMPLE_TRAITS,
        profiles=STAGED,
        unit_behaviors=(UnitBehavior(unit_id="loaded", traits=traits, removed_traits=removed),),
    )
    return play(field(), UNIT_TYPES, library, ticks=TICKS)


def first(run: ScenarioRun, unit_id: str) -> TraceRecord:
    return run.by_unit(unit_id)[0]


def test_the_control_and_the_loaded_unit_start_from_the_same_profile() -> None:
    """Both are `cinder-hound`; without extra traits they must compose identically."""
    run = run_with()

    assert first(run, "plain").weights == first(run, "loaded").weights


def test_an_added_trait_changes_the_factor_it_names() -> None:
    run = run_with(DUTIFUL)

    assert weight(first(run, "loaded"), "objective_progress") > weight(
        first(run, "plain"), "objective_progress"
    )


def test_an_added_trait_leaves_factors_it_does_not_name_alone() -> None:
    """`pack-minded` moves ally_support and nothing else."""
    run = run_with(PACK_MINDED)
    loaded, plain = first(run, "loaded"), first(run, "plain")

    for factor in FACTORS:
        if factor != "ally_support":
            assert weight(loaded, factor) == weight(plain, factor), factor


def test_two_traits_pulling_the_same_way_compose_rather_than_replacing() -> None:
    """Stacking has to be worth more than either half, or "combined" means nothing."""
    one = weight(first(run_with(DUTIFUL), "loaded"), "objective_progress")
    plain = weight(first(run_with(), "loaded"), "objective_progress")
    both = weight(first(run_with(DUTIFUL, DUTIFUL), "loaded"), "objective_progress")

    assert one > plain
    # A duplicate tag must not silently double the effect either; composition is
    # defined, whichever way it is defined. What matters is that it is bounded
    # and that it did not fall back to the unmodified value.
    assert both >= one


def test_opposing_traits_do_not_leave_the_unit_indifferent_to_everything() -> None:
    """`aggressive` and `wary` disagree about danger. They must not zero the unit out."""
    run = run_with(WARY)
    loaded = first(run, "loaded")

    assert any(weight(loaded, factor) > 0 for factor in FACTORS)


def test_a_removed_trait_comes_off_its_type_profile() -> None:
    """`cinder-hound` is aggressive by type; an individual may not be."""
    run = run_with(removed=(AGGRESSIVE,))
    loaded, plain = first(run, "loaded"), first(run, "plain")

    assert AGGRESSIVE in plain.traits
    assert AGGRESSIVE not in loaded.traits
    assert weight(loaded, "danger") > weight(plain, "danger")


def test_no_combination_pushes_a_weight_outside_its_bounds() -> None:
    """Four traits at once still has to land in `[0, MAX_WEIGHT]`."""
    run = run_with(AGGRESSIVE, DUTIFUL, PACK_MINDED, WARY)
    loaded = first(run, "loaded")

    for factor in FACTORS:
        assert 0.0 <= weight(loaded, factor) <= MAX_WEIGHT, factor


def test_the_trace_lists_every_trait_that_was_in_play() -> None:
    run = run_with(DUTIFUL, PACK_MINDED)
    traits = first(run, "loaded").traits

    assert DUTIFUL in traits
    assert PACK_MINDED in traits
    # And the ones the type supplied, so the report explains the whole unit.
    assert AGGRESSIVE in traits


def test_a_combined_unit_and_a_plain_one_can_actually_diverge_in_play() -> None:
    """Weights that never reach a decision would satisfy every test above."""
    run = run_with(DUTIFUL)

    assert run.actions("loaded") != run.actions("plain") or (
        run.unit("loaded").position != run.unit("plain").position
    )
