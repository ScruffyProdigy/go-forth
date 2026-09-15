"""Selecting: highest score, stable ties, and randomness only when asked for."""

from __future__ import annotations

from dataclasses import replace

from app.sim.ai.candidates import generate_candidates
from app.sim.ai.decide import _with_jitter, decide, intent_of
from app.sim.ai.factors import FACTORS, NEUTRAL_WEIGHTS, freeze_weights
from app.sim.ai.profiles import MAX_JITTER, ResolvedBehavior
from app.sim.ai.scoring import score_candidates
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


#: A post further down the lane, so "press on" is a real option to weigh
#: against "swing at what is in front of you".
STATION = Vec2(MIDFIELD.x, MIDFIELD.y + 100)


def engaged() -> tuple[World, Unit]:
    hound = make_unit("h", HOUND, "north", MIDFIELD, destination=STATION)
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


def test_total_indifference_resolves_the_same_way_every_single_time() -> None:
    """Indifference has to resolve the same way in a replay, or it is not one.

    It resolves to standing still rather than to the first candidate, which is a
    change from JQ-328's tie-break and a deliberate one: JQ-329 makes a *step*
    have to be clearly better than holding before a unit takes it, so a creature
    with no opinion about anything at all does not wander. See
    `decide._worth_moving` — the alternative was units vibrating on the spot
    wherever two forces balanced. The tie-break itself is unchanged and still
    settles ties among everything else.
    """
    world, hound = engaged()
    observation = look(world, hound)
    indifferent = behavior(**{factor: 0.0 for factor in FACTORS})

    first = decide(observation, indifferent)
    again = decide(observation, indifferent)

    assert first.selected == again.selected
    assert first.selected.kind == "hold"


def test_a_tie_between_two_swings_goes_to_the_earlier_candidate() -> None:
    """The tie-break proper, on candidates that standing still cannot displace.

    Two identical enemies in reach: nothing distinguishes the two attacks, so the
    earlier one in the stable order wins, and does so in every replay.
    """
    world, hound = engaged()
    observation = look(world, hound)
    indifferent = behavior(**{factor: 0.0 for factor in FACTORS})

    attacks = [
        entry.candidate
        for entry in decide(observation, indifferent).considered
        if entry.candidate.kind == "attack"
    ]

    assert attacks, "the fixture has nothing in reach; this test needs a fight"
    assert attacks == sorted(attacks, key=lambda c: c.target_id or "")


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


def test_jitter_preserves_every_field_of_the_record_it_rescores() -> None:
    """The jitter path must carry fields it has never heard of.

    It is the worst place in the package for a silent drop. No fixture sets
    `tie_break_jitter` above zero, so the path is dead in every battle anyone
    runs; a rebuild that forgot a field would keep every suite green and surface
    only when some future profile enabled jitter and the field read empty for the
    whole battle. JQ-331 found that hazard waiting in the merge with JQ-330,
    whose `influences` field would have vanished here.

    Asserted as whole-record equality with the score normalised away, so it is a
    claim about the *next* field as much as the current ones. Verified by
    rebuilding `_with_jitter` field-by-field on purpose, with a stand-in for
    JQ-330's `influences` populated per record, and watching this fail.

    Reaches for `_with_jitter` directly because the jittered records are not
    observable from outside: `Decision.considered` deliberately reports the real
    scores rather than the nudged ones, so a test that read them back through a
    decision would compare a tuple with itself and pass no matter what.
    """
    world, hound = engaged()
    observation = look(world, hound)
    scored = score_candidates(observation, generate_candidates(observation), NEUTRAL_WEIGHTS)
    assert scored, "the fixture produced no candidates to jitter"

    jittered = _with_jitter(scored, MAX_JITTER, create_rng(3))

    for before, after in zip(scored, jittered, strict=True):
        # Whole-record equality with the score normalised away, rather than a
        # field-by-field walk. The walk looks equivalent and is not: it compares
        # `after.x` against `before.x`, which both hold the field's *default*
        # when nothing populated it, so a rebuild that dropped the field would
        # match on every name and pass. Found by breaking `_with_jitter` on
        # purpose and watching the field-by-field version stay green — the
        # failure this test exists to catch, missed by the test written to catch
        # it. Comparing the records entire has no such blind spot and needs no
        # list of field names to keep in step.
        assert replace(after, score=before.score) == before, (
            "jitter did not carry the record intact; rebuild it with `replace`, not field by field"
        )
        assert after.score != before.score, "jitter changed nothing, so this proves nothing"


def test_jitter_left_at_zero_returns_the_very_same_records() -> None:
    """The common case does not rebuild anything at all, nor draw."""
    world, hound = engaged()
    observation = look(world, hound)
    scored = score_candidates(observation, generate_candidates(observation), NEUTRAL_WEIGHTS)

    assert _with_jitter(scored, 0.0, create_rng(3)) is scored
