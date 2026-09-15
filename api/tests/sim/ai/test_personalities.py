"""Composable mage personalities: contextual rules, strength, and combination.

The fixture every test here shares is one troop being shot at. A mage stands
behind a melee summon and a ranged one; a rooted mortar out-ranges all three and
is hitting the mage. That single arrangement is enough to ask every question the
ticket asks, because it is the arrangement where the four example personalities
genuinely disagree: there is something to intercept, a risk in intercepting it,
one ally worth protecting, and two units whose only legal ways of helping are
different from each other.
"""

from __future__ import annotations

import pytest

from app.sim.ai.candidates import Candidate, generate_candidates
from app.sim.ai.capabilities import capabilities_of
from app.sim.ai.decide import decide
from app.sim.ai.factors import FACTORS, FactorName
from app.sim.ai.fixtures import (
    METHODICAL,
    OPPORTUNISTIC,
    PROTECTIVE,
    RECKLESS,
    SAMPLE_PERSONALITIES,
    SAMPLE_PROFILES,
    SAMPLE_TRAITS,
    combined_library,
    contrasting_library,
    definitions,
    strength_library,
)
from app.sim.ai.observe import Observation
from app.sim.ai.profiles import (
    BehaviorLibrary,
    CoordinationInfluence,
    MagePersonality,
    PersonalityDefinition,
    PersonalityRef,
    PersonalityRule,
    ResolvedBehavior,
    defaulted,
    describe_behavior,
    index_library,
)
from app.sim.ai.scoring import ScoredCandidate, score_candidate
from app.sim.ai.vocabulary import PersonalityTag
from app.sim.types import Vec2
from app.sim.units import UnitType, build_unit_type_catalog
from app.sim.world import Unit, World
from tests.sim.ai.helpers import attach, look, make_unit, make_world
from tests.sim.fixtures_units import ADEPT, HOUND

#: Reaches further than it is reached. The threat the fixture is built around.
MORTAR = UnitType(
    id="slag-mortar",
    kind="summon",
    schools=("fire",),
    max_hp=80,
    damage=15,
    range=100,
    speed=0,
    attack_cooldown_seconds=2,
)
#: A summon that answers a threat by shooting rather than by walking.
SPRITE = UnitType(
    id="ember-sprite",
    kind="summon",
    schools=("fire",),
    max_hp=40,
    damage=9,
    range=70,
    speed=44,
    attack_cooldown_seconds=1.2,
)

TYPES = [ADEPT, HOUND, SPRITE, MORTAR]
CATALOG = build_unit_type_catalog(TYPES)

MAGE_AT = Vec2(180, 400)
THREAT_AT = Vec2(180, 320)
#: The post this troop is holding: between the two summons, a stride from each.
#:
#: Chosen so that stepping toward the mortar neither closes on the post nor
#: abandons it — objective progress comes out at roughly nothing for everybody.
#: Both of the obvious alternatives rig the answer. A post the units are already
#: standing on makes every advance score a full negative, so nobody intercepts
#: anything for any reason; a post beyond the mortar makes walking at it the
#: same move as obeying the order, so everybody "intercepts" and the personality
#: is not what decided it. The question these tests ask is what a mage's
#: disposition does, which means the objective has to be neutral about it.
STATION = Vec2(180, 385)


def escort(library: BehaviorLibrary | None = None) -> World:
    """The mage, its two summons, and the thing shooting at it."""
    world = make_world(
        [
            make_unit("m", ADEPT, "north", MAGE_AT, destination=STATION),
            make_unit("melee", HOUND, "north", Vec2(160, 380), destination=STATION),
            make_unit("ranged", SPRITE, "north", Vec2(200, 380), destination=STATION),
            make_unit("e", MORTAR, "south", THREAT_AT),
        ]
    )
    if library is not None:
        attach(world, library, TYPES)
    return world


def unit_of(world: World, unit_id: str) -> Unit:
    return next(u for u in world.units if u.id == unit_id)


def behavior_of(world: World, unit_id: str) -> ResolvedBehavior:
    ai = unit_of(world, unit_id).ai
    assert ai is not None
    return ai.behavior


def candidate_for(observation: Observation, kind: str, target_id: str | None) -> Candidate:
    return next(c for c in generate_candidates(observation) if c.kind == kind and c.target_id == target_id)


def scored(world: World, unit_id: str, kind: str, target_id: str | None) -> ScoredCandidate:
    observation = look(world, unit_of(world, unit_id))
    behavior = behavior_of(world, unit_id)
    return score_candidate(
        observation,
        candidate_for(observation, kind, target_id),
        behavior.weights,
        behavior.personalities,
    )


def weight_of(entry: ScoredCandidate, factor: FactorName) -> float:
    return next(c.weight for c in entry.contributions if c.factor == factor)


def contribution_of(entry: ScoredCandidate, factor: FactorName) -> float:
    return next(c.contribution for c in entry.contributions if c.factor == factor)


#: The candidate the whole fixture exists to ask about: the melee summon walking
#: at the thing that is shooting its mage. An interception, in the only terms a
#: melee summon has for one.
INTERCEPT = ("melee", "advance", "e")


# --- strength: default, zero, and raised -------------------------------------


def test_an_omitted_strength_resolves_to_the_definitions_default() -> None:
    omitted = behavior_of(escort(strength_library("m", PROTECTIVE)), "melee")
    spelled_out = behavior_of(escort(strength_library("m", PROTECTIVE, strength=1.0)), "melee")

    assert omitted.weights == spelled_out.weights
    assert omitted.personalities[0].strength == spelled_out.personalities[0].strength
    assert omitted.personalities[0].rules == spelled_out.personalities[0].rules


def test_the_record_still_says_which_of_those_two_it_was() -> None:
    """Identical behavior, different provenance. JQ-331 prints the difference."""
    omitted = behavior_of(escort(strength_library("m", PROTECTIVE)), "melee")
    spelled_out = behavior_of(escort(strength_library("m", PROTECTIVE, strength=1.0)), "melee")

    assert defaulted(omitted.personalities[0])
    assert not defaulted(spelled_out.personalities[0])
    assert [s.mage_id for s in omitted.personalities[0].sources] == ["m"]


def test_zero_strength_removes_the_contribution_rather_than_inverting_it() -> None:
    silent = escort(strength_library("m", PROTECTIVE, strength=0.0))
    absent = escort(BehaviorLibrary(personalities=SAMPLE_PERSONALITIES))

    assert behavior_of(silent, "melee").weights == behavior_of(absent, "melee").weights
    assert scored(silent, *INTERCEPT).influences == ()
    # And it is still on the record, rather than looking un-authored.
    assert behavior_of(silent, "melee").personalities[0].tag == PROTECTIVE


def test_a_stronger_override_raises_that_tags_contribution_in_its_own_context() -> None:
    ordinary = scored(escort(strength_library("m", PROTECTIVE)), *INTERCEPT)
    insistent = scored(escort(strength_library("m", PROTECTIVE, strength=2.0)), *INTERCEPT)

    assert contribution_of(insistent, "target_suitability") > contribution_of(ordinary, "target_suitability")


def test_a_stronger_override_changes_nothing_in_a_context_the_tag_is_silent_in() -> None:
    """Holding still, with nobody aimed at: protective has nothing to say."""
    ordinary = scored(escort(strength_library("m", PROTECTIVE)), "melee", "hold", None)
    insistent = scored(escort(strength_library("m", PROTECTIVE, strength=2.0)), "melee", "hold", None)

    assert [c.weight for c in insistent.contributions] == [c.weight for c in ordinary.contributions]
    assert insistent.score == ordinary.score
    assert insistent.influences == ()


def test_a_creature_already_at_the_floor_cannot_be_talked_into_being_bolder() -> None:
    """Part of the strength range is unreachable for some creatures, by design.

    The cinder-hound opens at danger 0.75 and `aggressive` takes 0.5 off, so a
    reckless mage at any strength above 0.42 drives its danger weight to the
    floor on a candidate that tag speaks to. Raising the mage from 1.0 to 2.0
    then changes nothing about that candidate. The clamp is deliberate —
    `factors.py` is explicit that a weight never goes negative, because a
    negative one would mean a creature that actively seeks harm — so this is a
    property to know rather than a bug to fix.

    What contextual rules *did* fix is the leak. The tag now only saturates
    inside the situations it speaks to: the hound's standing weight survives, so
    it is still the same creature when it is standing still, rather than
    fearless everywhere for the whole battle.
    """
    hound_only = tuple(p for p in SAMPLE_PROFILES if p.type_id == HOUND.id)

    def led(strength: float) -> World:
        return escort(
            BehaviorLibrary(
                traits=SAMPLE_TRAITS,
                personalities=SAMPLE_PERSONALITIES,
                profiles=hound_only,
                mage_personalities=(MagePersonality("m", (PersonalityRef(RECKLESS, strength=strength),)),),
            )
        )

    ordinary, insistent = led(1.0), led(2.0)

    assert weight_of(scored(ordinary, *INTERCEPT), "danger") == 0.0
    assert weight_of(scored(insistent, *INTERCEPT), "danger") == 0.0
    # And the context it does not speak to keeps the creature's own opinion.
    assert weight_of(scored(insistent, "melee", "hold", None), "danger") > 0.0
    assert behavior_of(insistent, "melee").weights["danger"] > 0.0


def test_a_strength_outside_the_validated_bounds_is_refused() -> None:
    with pytest.raises(ValueError, match="strength runs"):
        index_library(strength_library("m", PROTECTIVE, strength=99.0), CATALOG)


# --- the combination that used to cancel -------------------------------------


def test_reckless_and_protective_both_survive_being_the_same_mage() -> None:
    """The headline. One aggression slider makes this pair add to nothing.

    Reckless discounts danger at the moment of commitment; protective raises
    what an ally's attacker is worth and accepts the risk of stepping in. On an
    interception both speak, so the combined unit must be visibly further from
    neutral than either tag alone leaves it — not back where it started.
    """
    plain = scored(escort(BehaviorLibrary(personalities=SAMPLE_PERSONALITIES)), *INTERCEPT)
    combined = scored(escort(combined_library("m")), *INTERCEPT)

    assert weight_of(combined, "danger") < weight_of(plain, "danger")
    assert weight_of(combined, "target_suitability") > weight_of(plain, "target_suitability")


def test_the_combination_is_more_willing_than_either_half_alone() -> None:
    reckless = scored(escort(strength_library("m", RECKLESS)), *INTERCEPT)
    protective = scored(escort(strength_library("m", PROTECTIVE)), *INTERCEPT)
    combined = scored(escort(combined_library("m")), *INTERCEPT)

    # Danger: both discount it here, so together they discount it further.
    assert weight_of(combined, "danger") < min(weight_of(reckless, "danger"), weight_of(protective, "danger"))
    # Suitability: protective is the one that knows why this target matters, and
    # reckless does not talk it back down.
    assert weight_of(combined, "target_suitability") >= weight_of(protective, "target_suitability")


def test_both_tags_are_named_in_the_record_for_the_candidate_they_shaped() -> None:
    influences = scored(escort(combined_library("m")), *INTERCEPT).influences

    assert {i.tag for i in influences} == {RECKLESS, PROTECTIVE}
    assert {i.context for i in influences} == {"closing", "ally-threatened"}
    assert all(i.factor in FACTORS for i in influences)


def test_the_contrasting_library_puts_one_tag_on_each_of_two_mages() -> None:
    index = index_library(contrasting_library("north-t0-u0", "north-t1-u0"), CATALOG)

    assert [ref.tag for ref in index.mage_personalities["north-t0-u0"]] == [RECKLESS]
    assert [ref.tag for ref in index.mage_personalities["north-t1-u0"]] == [METHODICAL]


def test_contrasting_mages_lead_the_same_entourage_differently() -> None:
    """Two profiles, one fixture, and a difference that is the mage's doing."""
    reckless = scored(escort(strength_library("m", RECKLESS)), *INTERCEPT)
    methodical = scored(escort(strength_library("m", METHODICAL)), *INTERCEPT)

    assert weight_of(reckless, "danger") < weight_of(methodical, "danger")
    assert reckless.score != methodical.score


# --- motivation and execution are different things ---------------------------


def test_one_ally_threat_wakes_the_same_rule_in_both_units() -> None:
    """Motivation is shared; nothing about it is written per fighting style.

    One authored rule — protective's `ally-threatened` — fires on the guard's
    advance and on the archer's attack. Neither `advance` nor `attack` appears
    anywhere in that rule: what each unit is offered came out of its own reach,
    and the rule spoke to whichever of those the unit had.
    """
    world = escort(combined_library("m"))

    guard = scored(world, "melee", "advance", "e")
    archer = scored(world, "ranged", "attack", "e")

    assert (PROTECTIVE, "ally-threatened") in {(i.tag, i.context) for i in guard.influences}
    assert (PROTECTIVE, "ally-threatened") in {(i.tag, i.context) for i in archer.influences}


def test_each_unit_is_offered_only_what_its_reach_allows() -> None:
    """And so the same motivation comes out as a walk and as a shot."""
    world = escort(combined_library("m"))

    guard_options = {(c.kind, c.target_id) for c in generate_candidates(look(world, unit_of(world, "melee")))}
    archer_options = {
        (c.kind, c.target_id) for c in generate_candidates(look(world, unit_of(world, "ranged")))
    }

    assert ("attack", "e") not in guard_options
    assert ("advance", "e") in guard_options
    assert ("attack", "e") in archer_options


def test_the_archer_answers_without_moving_and_the_personality_widens_the_gap() -> None:
    plain = escort(BehaviorLibrary(personalities=SAMPLE_PERSONALITIES))
    led = escort(combined_library("m"))

    assert decide(look(led, unit_of(led, "ranged")), behavior_of(led, "ranged")).selected.kind == "attack"

    def preference(world: World) -> float:
        return scored(world, "ranged", "attack", "e").score - scored(world, "ranged", "advance", "e").score

    assert preference(led) > preference(plain)


def test_protective_lifts_an_interception_further_above_standing_still() -> None:
    """Each tag adds to the case for stepping in, and neither undoes the other."""

    def margin(library: BehaviorLibrary) -> float:
        world = escort(library)
        return scored(world, *INTERCEPT).score - scored(world, "melee", "hold", None).score

    plain = margin(BehaviorLibrary(personalities=SAMPLE_PERSONALITIES))
    protective = margin(strength_library("m", PROTECTIVE))
    combined = margin(combined_library("m"))

    assert plain < protective < combined


def test_an_interception_cannot_yet_outrank_the_troops_own_post() -> None:
    """A boundary worth pinning, because it looks like a tuning failure and is not.

    `objective_progress` saturates: any advance *at* the station scores a flat
    1.0 on it, because the station is what the factor measures progress toward.
    An interception is an advance at something else, so the best it can score
    there is nothing — and a unit still walking to its post therefore prefers
    the post, at every strength a personality can reach.

    That is faithful to what this ticket owns. Motivation is here; the missing
    piece is a *position* that answers the threat without abandoning the post,
    which is screening, which is JQ-329's. Anyone who reads a guard walking past
    a mortar to reach its station and reaches for protective's numbers will be
    turning the wrong dial until that candidate exists.
    """
    world = escort(strength_library("m", PROTECTIVE, strength=2.0))

    assert scored(world, "melee", "advance", None).score > scored(world, *INTERCEPT).score


def test_a_mages_personality_reaches_its_summons_without_touching_their_stats() -> None:
    plain = escort(BehaviorLibrary(personalities=SAMPLE_PERSONALITIES))
    led = escort(combined_library("m"))

    assert [p.tag for p in behavior_of(led, "melee").personalities] == [PROTECTIVE, RECKLESS]
    assert behavior_of(plain, "melee").personalities == ()
    assert capabilities_of(unit_of(led, "melee")) == capabilities_of(unit_of(plain, "melee"))


def test_a_purely_contextual_tag_leaves_the_standing_weights_alone() -> None:
    """Worth knowing before reading a composition: it can look like nothing happened.

    Neither reckless nor protective has a context-free opinion, so a unit under
    both composes to exactly the weights it would hold under neither. The whole
    of what they do arrives per candidate — so a test that compares standing
    weights to prove a personality landed will pass identically whether it did
    or not, and the thing to compare is the scored candidate.

    This is not hypothetical. JQ-331's inspector scenarios read the standing set
    and concluded a working personality did nothing; three tests failed on where
    the effect lives rather than on its size or direction. Hence the blunt table
    on `ResolvedBehavior`, and hence the last assertion here — `personalities`
    being non-empty is the signal that a tag landed, and it is the check to make
    when the weights look untouched.
    """
    plain = escort(BehaviorLibrary(personalities=SAMPLE_PERSONALITIES))
    led = escort(combined_library("m"))

    assert behavior_of(led, "melee").weights == behavior_of(plain, "melee").weights
    assert scored(led, *INTERCEPT).influences != scored(plain, *INTERCEPT).influences
    assert behavior_of(led, "melee").personalities
    assert not behavior_of(plain, "melee").personalities


# --- exceptions, and the dimensions a rule composes on -----------------------

WATCHFUL = PersonalityTag("watchful")


def with_rule(*rules: PersonalityRule) -> BehaviorLibrary:
    return BehaviorLibrary(
        personalities=(PersonalityDefinition(WATCHFUL, default_strength=1.0, rules=rules),),
        mage_personalities=(MagePersonality("m", (PersonalityRef(WATCHFUL),)),),
    )


def test_a_rule_scoped_to_one_action_is_silent_on_every_other() -> None:
    library = with_rule(PersonalityRule(when="closing", weights={"danger": -1.0}, actions=("attack",)))
    entry = scored(escort(library), *INTERCEPT)

    assert entry.influences == ()


def test_an_exception_silences_a_rule_that_would_otherwise_fire() -> None:
    firing = with_rule(PersonalityRule(when="closing", weights={"danger": -1.0}))
    silenced = with_rule(
        PersonalityRule(when="closing", weights={"danger": -1.0}, unless=("ally-threatened",))
    )

    assert scored(escort(firing), *INTERCEPT).influences != ()
    assert scored(escort(silenced), *INTERCEPT).influences == ()


def test_influence_range_decides_how_far_a_rule_looks_for_the_situation() -> None:
    """The mage is 28 units from the guard. A rule that looks 10 cannot see it."""
    near = with_rule(
        PersonalityRule(when="ally-threatened", weights={"target_suitability": 1.0}, influence=10.0)
    )
    far = with_rule(
        PersonalityRule(when="ally-threatened", weights={"target_suitability": 1.0}, influence=90.0)
    )

    assert scored(escort(near), *INTERCEPT).influences == ()
    assert scored(escort(far), *INTERCEPT).influences != ()


def test_two_rules_that_both_fire_both_apply() -> None:
    """Summation, not precedence, and not the later one winning."""
    one = with_rule(PersonalityRule(when="closing", weights={"danger": -0.5}))
    two = with_rule(
        PersonalityRule(when="closing", weights={"danger": -0.5}),
        PersonalityRule(when="ally-threatened", weights={"danger": -0.5}, influence=90.0),
    )

    assert weight_of(scored(escort(two), *INTERCEPT), "danger") < weight_of(
        scored(escort(one), *INTERCEPT), "danger"
    )


# --- what a rule may not be --------------------------------------------------


def test_a_rule_that_moves_no_priority_is_refused() -> None:
    with pytest.raises(ValueError, match="moves no priorities"):
        index_library(with_rule(PersonalityRule(when="closing")), CATALOG)


def test_a_rule_silenced_by_its_own_situation_is_refused() -> None:
    with pytest.raises(ValueError, match="silenced by the very situation"):
        index_library(
            with_rule(PersonalityRule(when="closing", weights={"danger": -1.0}, unless=("closing",))),
            CATALOG,
        )


def test_a_rule_that_looks_across_the_whole_map_is_refused() -> None:
    with pytest.raises(ValueError, match="describing the battle"):
        index_library(
            with_rule(PersonalityRule(when="closing", weights={"danger": -1.0}, influence=10_000.0)),
            CATALOG,
        )


def test_a_rule_naming_a_situation_the_sim_cannot_answer_is_refused() -> None:
    with pytest.raises(ValueError, match="is not a context"):
        index_library(
            with_rule(PersonalityRule(when="feeling-lucky", weights={"danger": -1.0})),  # type: ignore[arg-type]
            CATALOG,
        )


def test_a_tag_that_changes_nothing_at_all_is_refused() -> None:
    """It would still show up in every diagnostic as though it had done something."""
    with pytest.raises(ValueError, match="says nothing"):
        index_library(
            BehaviorLibrary(personalities=(PersonalityDefinition(WATCHFUL, default_strength=1.0),)),
            CATALOG,
        )


def test_a_coordination_habit_outside_its_bounds_is_refused() -> None:
    with pytest.raises(ValueError, match="the bound is"):
        index_library(
            BehaviorLibrary(
                personalities=(
                    PersonalityDefinition(
                        WATCHFUL,
                        default_strength=1.0,
                        coordination=CoordinationInfluence(guard_radius=10_000.0),
                    ),
                )
            ),
            CATALOG,
        )


# --- the plain-language half -------------------------------------------------


def test_every_selected_personality_gets_one_line_a_person_could_read() -> None:
    lines = describe_behavior(behavior_of(escort(combined_library("m")), "melee"))

    assert len(lines) == 2
    assert any(line.startswith(f"{PROTECTIVE}:") for line in lines)
    assert any(line.startswith(f"{RECKLESS}:") for line in lines)
    assert all(line.endswith(".") for line in lines)


def test_a_line_says_the_strength_out_loud_only_when_it_was_chosen() -> None:
    default = describe_behavior(behavior_of(escort(strength_library("m", PROTECTIVE)), "melee"))
    dialled = describe_behavior(behavior_of(escort(strength_library("m", PROTECTIVE, strength=1.5)), "melee"))

    assert "Dialled" not in default[0]
    assert "Dialled to 1.5" in dialled[0]


def test_a_silenced_tag_says_so_rather_than_repeating_its_summary() -> None:
    lines = describe_behavior(
        behavior_of(escort(strength_library("m", OPPORTUNISTIC, strength=0.0)), "melee")
    )

    assert lines == (f"{OPPORTUNISTIC}: dialled to zero, so it says nothing here.",)


def test_every_shipped_personality_has_a_summary_to_print() -> None:
    """A tag with no line would reach the UI as its own id, which is not English."""
    for definition in SAMPLE_PERSONALITIES:
        assert definition.summary
        assert definition.summary.endswith(".")


def test_the_shipped_definitions_are_internally_consistent() -> None:
    index_library(definitions(), CATALOG)
