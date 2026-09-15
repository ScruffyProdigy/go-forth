"""Scoring: four bounded, comparable verdicts, and the contributions behind them."""

from __future__ import annotations

import pytest

from app.sim.ai.candidates import Candidate, generate_candidates
from app.sim.ai.factors import FACTORS, MAX_WEIGHT, FactorName, freeze_weights
from app.sim.ai.objective import ObjectiveFixtures
from app.sim.ai.scoring import ScoredCandidate, score_candidate, score_candidates
from app.sim.types import Vec2
from tests.sim.ai.helpers import look, make_unit, make_world
from tests.sim.fixtures_units import ADEPT, HOUND

MIDFIELD = Vec2(180, 300)
EVEN = freeze_weights({factor: 1.0 for factor in FACTORS})


def raw_of(scored: ScoredCandidate, factor: FactorName) -> float:
    return next(c.raw for c in scored.contributions if c.factor == factor)


# --- objective progress -----------------------------------------------------


def test_advancing_toward_the_station_scores_positively() -> None:
    hound = make_unit("h", HOUND, "north", MIDFIELD)
    world = make_world([hound])
    station = Vec2(MIDFIELD.x, MIDFIELD.y + 100)

    scored = score_candidate(
        look(world, hound, ObjectiveFixtures(stations={"north-t0": station})),
        Candidate(kind="advance", destination=station),
        EVEN,
    )

    assert raw_of(scored, "objective_progress") == pytest.approx(1.0)


def test_walking_away_from_the_station_scores_negatively() -> None:
    """How a unit with a heavy objective weight refuses to chase backwards."""
    hound = make_unit("h", HOUND, "north", MIDFIELD)
    world = make_world([hound])
    station = Vec2(MIDFIELD.x, MIDFIELD.y + 100)
    behind = Vec2(MIDFIELD.x, MIDFIELD.y - 100)

    scored = score_candidate(
        look(world, hound, ObjectiveFixtures(stations={"north-t0": station})),
        Candidate(kind="advance", destination=behind),
        EVEN,
    )

    assert raw_of(scored, "objective_progress") < 0


def test_holding_and_attacking_score_zero_on_progress_rather_than_negative() -> None:
    """Standing your ground is not advancing; it is also not retreating."""
    hound = make_unit("h", HOUND, "north", MIDFIELD)
    world = make_world([hound, make_unit("e", HOUND, "south", Vec2(MIDFIELD.x + 10, MIDFIELD.y))])
    observation = look(world, hound)

    for candidate in (Candidate(kind="hold", destination=MIDFIELD), Candidate(kind="attack", target_id="e")):
        assert raw_of(score_candidate(observation, candidate, EVEN), "objective_progress") == 0.0


# --- target suitability -----------------------------------------------------


def test_a_target_this_swing_would_finish_outscores_a_healthy_one() -> None:
    hound = make_unit("h", HOUND, "north", MIDFIELD)
    nearly_dead = make_unit("e-weak", HOUND, "south", Vec2(MIDFIELD.x + 10, MIDFIELD.y), hp=1)
    healthy = make_unit("e-full", HOUND, "south", Vec2(MIDFIELD.x + 10, MIDFIELD.y))
    world = make_world([hound, nearly_dead, healthy])
    observation = look(world, hound)

    weak = score_candidate(observation, Candidate(kind="attack", target_id="e-weak"), EVEN)
    full = score_candidate(observation, Candidate(kind="attack", target_id="e-full"), EVEN)

    assert raw_of(weak, "target_suitability") > raw_of(full, "target_suitability")


def test_a_harder_hitting_target_is_worth_silencing_first() -> None:
    adept = make_unit("a", ADEPT, "north", MIDFIELD)
    spot = Vec2(MIDFIELD.x + 10, MIDFIELD.y)
    dangerous = make_unit("e-hound", HOUND, "south", spot)
    harmless = make_unit("e-adept", ADEPT, "south", spot)
    world = make_world([adept, dangerous, harmless])
    observation = look(world, adept)

    hound_score = score_candidate(observation, Candidate(kind="attack", target_id="e-hound"), EVEN)
    adept_score = score_candidate(observation, Candidate(kind="attack", target_id="e-adept"), EVEN)

    assert raw_of(hound_score, "target_suitability") > raw_of(adept_score, "target_suitability")


# --- danger -----------------------------------------------------------------


def test_danger_is_measured_where_the_candidate_would_leave_you() -> None:
    """Not where you are now — otherwise every advance would look equally safe."""
    hound = make_unit("h", HOUND, "north", Vec2(180, 200))
    ambush = make_unit("e", ADEPT, "south", Vec2(180, 260))
    world = make_world([hound, ambush])
    observation = look(world, hound)

    toward = score_candidate(observation, Candidate(kind="advance", destination=ambush.position), EVEN)
    away = score_candidate(observation, Candidate(kind="advance", destination=Vec2(180, 100)), EVEN)

    assert raw_of(toward, "danger") < raw_of(away, "danger")


def test_the_same_spot_is_more_dangerous_to_a_unit_that_is_already_hurt() -> None:
    """The durability term. A wary trait backs off a wounded creature, not a fresh one."""
    spot = Vec2(180, 300)
    enemy = make_unit("e", ADEPT, "south", Vec2(180, 320))

    def danger(hp: float) -> float:
        hound = make_unit("h", HOUND, "north", spot, hp=hp)
        world = make_world([hound, enemy])
        return raw_of(
            score_candidate(look(world, hound), Candidate(kind="hold", destination=spot), EVEN), "danger"
        )

    assert danger(HOUND.max_hp / 5) < danger(HOUND.max_hp)


# --- ally support -----------------------------------------------------------


def test_company_scores_better_than_being_alone() -> None:
    def support(allies: int) -> float:
        hound = make_unit("h", HOUND, "north", MIDFIELD)
        friends = [make_unit(f"f{i}", HOUND, "north", MIDFIELD) for i in range(allies)]
        world = make_world([hound, *friends])
        return raw_of(
            score_candidate(look(world, hound), Candidate(kind="hold", destination=MIDFIELD), EVEN),
            "ally_support",
        )

    assert support(0) == 0.0
    assert support(2) > support(0)


def test_an_ally_in_another_troop_counts_for_less_than_one_of_your_own() -> None:
    """Support is local and mandatory inside a troop (design doc 4.2)."""

    def support(troop_id: str) -> float:
        hound = make_unit("h", HOUND, "north", MIDFIELD, troop_id="north-t0")
        friend = make_unit("f", HOUND, "north", MIDFIELD, troop_id=troop_id)
        world = make_world([hound, friend])
        return raw_of(
            score_candidate(look(world, hound), Candidate(kind="hold", destination=MIDFIELD), EVEN),
            "ally_support",
        )

    assert support("north-t0") > support("north-t1")


# --- boundedness and diagnostics --------------------------------------------


def test_every_score_stays_inside_the_bounds_however_heavy_the_weights() -> None:
    """A maxed-out creature is opinionated, not loud. The mean is what bounds it."""
    hound = make_unit("h", HOUND, "north", MIDFIELD, hp=1)
    world = make_world(
        [hound]
        + [make_unit(f"e{i}", ADEPT, "south", Vec2(MIDFIELD.x + 5, MIDFIELD.y)) for i in range(8)]
        + [make_unit(f"f{i}", HOUND, "north", MIDFIELD) for i in range(8)]
    )
    observation = look(world, hound)
    heavy = freeze_weights({factor: MAX_WEIGHT for factor in FACTORS})

    for scored in score_candidates(observation, generate_candidates(observation), heavy):
        assert -1.0 <= scored.score <= 1.0
        for contribution in scored.contributions:
            assert -1.0 <= contribution.raw <= 1.0


def test_every_factor_is_reported_even_when_it_had_nothing_to_say() -> None:
    """JQ-331 explains a decision by reading these back, so none may be missing."""
    hound = make_unit("h", HOUND, "north", MIDFIELD)
    world = make_world([hound])
    scored = score_candidate(look(world, hound), Candidate(kind="hold", destination=MIDFIELD), EVEN)

    assert tuple(c.factor for c in scored.contributions) == FACTORS


def test_a_weight_of_zero_removes_a_factor_s_say_without_removing_its_record() -> None:
    hound = make_unit("h", HOUND, "north", Vec2(180, 200))
    world = make_world([hound, make_unit("e", ADEPT, "south", Vec2(180, 260))])
    observation = look(world, hound)
    candidate = Candidate(kind="advance", destination=Vec2(180, 260))

    indifferent = freeze_weights(
        {"objective_progress": 1.0, "target_suitability": 1.0, "danger": 0.0, "ally_support": 1.0}
    )
    scored = score_candidate(observation, candidate, indifferent)
    danger = next(c for c in scored.contributions if c.factor == "danger")

    assert danger.raw < 0
    assert danger.contribution == 0.0


def test_a_unit_that_cares_about_nothing_scores_everything_the_same() -> None:
    hound = make_unit("h", HOUND, "north", MIDFIELD)
    world = make_world([hound, make_unit("e", HOUND, "south", Vec2(MIDFIELD.x + 10, MIDFIELD.y))])
    observation = look(world, hound)
    nothing = freeze_weights({factor: 0.0 for factor in FACTORS})

    scores = {s.score for s in score_candidates(observation, generate_candidates(observation), nothing)}

    assert scores == {0.0}
