"""Selecting: highest score, stable ties, and randomness only when asked for."""

from __future__ import annotations

from app.sim.ai.decide import decide, intent_of
from app.sim.ai.factors import FACTORS, freeze_weights
from app.sim.ai.profiles import ResolvedBehavior
from app.sim.rng import create_rng
from app.sim.types import Vec2
from app.sim.world import Unit, World
from tests.sim.ai.helpers import look, make_unit, make_world
from tests.sim.fixtures_units import ADEPT, HOUND

MIDFIELD = Vec2(180, 300)


def behavior(jitter: float = 0.0, **weights: float) -> ResolvedBehavior:
    return ResolvedBehavior(
        weights=freeze_weights({factor: weights.get(factor, 1.0) for factor in FACTORS}),
        tie_break_jitter=jitter,
    )


def engaged() -> tuple[World, Unit]:
    hound = make_unit("h", HOUND, "north", MIDFIELD)
    enemy = make_unit("e", HOUND, "south", Vec2(MIDFIELD.x + 10, MIDFIELD.y))
    return make_world([hound, enemy]), hound


def test_a_unit_that_only_cares_about_kills_attacks_what_is_in_reach() -> None:
    world, hound = engaged()

    decision = decide(
        look(world, hound), behavior(target_suitability=4.0, objective_progress=0.0, danger=0.0)
    )

    assert decision.selected.kind == "attack"
    assert decision.selected.target_id == "e"


def test_a_unit_that_only_cares_about_the_objective_walks_past_the_fight() -> None:
    """Same unit, same field, same stats. Only the weights differ."""
    world, hound = engaged()

    decision = decide(
        look(world, hound), behavior(objective_progress=4.0, target_suitability=0.0, danger=0.0)
    )

    assert decision.selected.kind == "advance"


def test_every_candidate_considered_is_reported_not_just_the_winner() -> None:
    world, hound = engaged()

    decision = decide(look(world, hound), behavior())

    assert len(decision.considered) > 1
    assert decision.selected in [scored.candidate for scored in decision.considered]


def test_the_winner_s_contributions_come_back_with_it() -> None:
    world, hound = engaged()

    decision = decide(look(world, hound), behavior())

    assert tuple(c.factor for c in decision.contributions) == FACTORS


def test_a_tie_goes_to_the_earlier_candidate_every_single_time() -> None:
    """Indifference has to resolve the same way in a replay, or it is not one."""
    world, hound = engaged()
    observation = look(world, hound)
    indifferent = behavior(**{factor: 0.0 for factor in FACTORS})

    first = decide(observation, indifferent)
    again = decide(observation, indifferent)

    assert first.selected == again.selected == first.considered[0].candidate


def test_a_profile_with_no_jitter_draws_no_randomness_at_all() -> None:
    """So a battle of ordinary creatures does not perturb the stream for others."""
    world, hound = engaged()
    rng = create_rng(7)
    before = rng.state

    decide(look(world, hound), behavior(), rng)

    assert rng.state == before


def test_jitter_draws_from_the_seeded_generator_and_replays_identically() -> None:
    world, hound = engaged()
    jittery = behavior(jitter=0.2)

    one = decide(look(world, hound), jittery, create_rng(11))
    other = decide(look(world, hound), jittery, create_rng(11))

    assert one.selected == other.selected
    assert one.score == other.score


def test_jitter_on_a_different_seed_is_free_to_choose_differently() -> None:
    """Otherwise the setting would cost randomness and buy nothing."""
    world, hound = engaged()
    jittery = behavior(jitter=0.25, **{factor: 0.0 for factor in FACTORS})

    scores = {decide(look(world, hound), jittery, create_rng(seed)).score for seed in range(6)}

    assert len(scores) > 1


def test_an_intent_carries_what_the_executing_phases_need() -> None:
    world, hound = engaged()

    chooser = behavior(target_suitability=4.0, objective_progress=0.0, danger=0.0)
    attack = intent_of(decide(look(world, hound), chooser))

    assert attack.kind == "attack"
    assert attack.target_id == "e"


def test_a_unit_with_nothing_to_do_still_produces_an_intent() -> None:
    adept = make_unit("a", ADEPT, "north", MIDFIELD)
    world = make_world([adept])
    adept.speed = 0

    decision = decide(look(world, adept), behavior())

    assert decision.selected.kind == "hold"
    assert intent_of(decision).destination == MIDFIELD
