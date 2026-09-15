"""Composing behavior data: defaults, overrides, personalities, and the rules."""

from __future__ import annotations

import copy

import pytest

from app.sim.ai.attach import attach_behavior
from app.sim.ai.capabilities import capabilities_of
from app.sim.ai.factors import FACTORS, MAX_WEIGHT, FactorName
from app.sim.ai.profiles import (
    MAX_STRENGTH,
    BehaviorLibrary,
    CreatureProfile,
    MagePersonality,
    PersonalityDefinition,
    PersonalityRef,
    PersonalityTag,
    TraitDefinition,
    TraitTag,
    UnitBehavior,
    defaulted,
    index_library,
    personality_refs_for_troop,
    resolve_behavior,
)
from app.sim.types import Vec2
from app.sim.units import build_unit_type_catalog
from tests.sim.ai.helpers import attach, make_unit, make_world
from tests.sim.fixtures_units import ADEPT, HOUND, WISP

HERE = Vec2(100, 100)
CATALOG = build_unit_type_catalog([ADEPT, HOUND, WISP])

BOLD = TraitTag("bold")
WARY = TraitTag("wary")
SHARPSHOOTER = TraitTag("sharpshooter")

RECKLESS = PersonalityTag("reckless")
CAREFUL = PersonalityTag("careful")

DEFINITIONS = BehaviorLibrary(
    traits=(
        TraitDefinition(BOLD, {"danger": -1.0, "target_suitability": 0.5}),
        TraitDefinition(WARY, {"danger": 1.0}),
        TraitDefinition(SHARPSHOOTER, {"target_suitability": 1.0}, requires=("ranged_attack",)),
    ),
    personalities=(
        PersonalityDefinition(RECKLESS, default_strength=1.0, weights={"danger": -1.0}),
        PersonalityDefinition(CAREFUL, default_strength=0.5, weights={"danger": 1.0}),
    ),
)


def library(
    profiles: tuple[CreatureProfile, ...] = (),
    unit_behaviors: tuple[UnitBehavior, ...] = (),
    mage_personalities: tuple[MagePersonality, ...] = (),
) -> BehaviorLibrary:
    """The shared definitions, plus whatever this test wants applied to them."""
    return BehaviorLibrary(
        traits=DEFINITIONS.traits,
        personalities=DEFINITIONS.personalities,
        profiles=profiles,
        unit_behaviors=unit_behaviors,
        mage_personalities=mage_personalities,
    )


def weights_for(lib: BehaviorLibrary, unit_id: str = "north-t0-u1") -> dict[FactorName, float]:
    world = make_world(
        [
            make_unit("north-t0-u0", ADEPT, "north", HERE),
            make_unit("north-t0-u1", HOUND, "north", HERE),
        ]
    )
    attach(world, lib, [ADEPT, HOUND])
    unit = next(u for u in world.units if u.id == unit_id)
    assert unit.ai is not None
    return dict(unit.ai.behavior.weights)


# --- defaults, overrides, composition ---------------------------------------


def unmodified() -> dict[FactorName, float]:
    """The hound with no profile and no traits: its own ability contour.

    Composition tests measure against this rather than against fixed numbers, so
    they go on testing composition when the contour is retuned.
    """
    return weights_for(library())


def test_a_creature_with_no_profile_still_fights_like_its_stat_block() -> None:
    """The contour is the default, which is what makes authoring optional.

    Two cards from the same roster, neither with a profile, compared against
    each other rather than against fixed numbers — so this keeps meaning the same
    thing if the contour is retuned. None of what it asserts is written down
    anywhere: it is read off the stat blocks.
    """
    hound = weights_for(library(), "north-t0-u1")
    adept = weights_for(library(), "north-t0-u0")

    assert hound != {factor: 1.0 for factor in FACTORS}
    # The hound hits twice as hard, so a good target is worth more to it.
    assert hound["target_suitability"] > adept["target_suitability"]
    # And moves twice as fast, so ground is worth more to it too.
    assert hound["objective_progress"] > adept["objective_progress"]
    # The adept is the sturdiest card here, so it needs company least.
    assert adept["ally_support"] < hound["ally_support"]


def test_an_unmentioned_factor_stays_neutral_rather_than_dropping_to_zero() -> None:
    """Writing one weight is not a statement about the other three."""
    weights = weights_for(library(profiles=(CreatureProfile("cinder-hound", {"danger": 0.25}),)))

    assert weights["danger"] == 0.25
    assert weights["ally_support"] == unmodified()["ally_support"]


def test_an_individual_can_add_a_trait_its_type_does_not_have() -> None:
    plain = weights_for(library(profiles=(CreatureProfile("cinder-hound"),)))
    skittish = weights_for(
        library(
            profiles=(CreatureProfile("cinder-hound"),),
            unit_behaviors=(UnitBehavior("north-t0-u1", traits=(WARY,)),),
        )
    )

    assert skittish["danger"] == plain["danger"] + 1.0


def test_an_individual_can_shed_a_trait_its_type_has() -> None:
    bold_by_default = library(profiles=(CreatureProfile("cinder-hound", traits=(BOLD,)),))
    weights = weights_for(
        library(
            profiles=(CreatureProfile("cinder-hound", traits=(BOLD,)),),
            unit_behaviors=(UnitBehavior("north-t0-u1", removed_traits=(BOLD,)),),
        )
    )

    assert weights_for(bold_by_default)["danger"] == unmodified()["danger"] - 1.0
    assert weights["danger"] == unmodified()["danger"]


# --- conflict handling ------------------------------------------------------


def test_opposing_traits_sum_rather_than_one_of_them_winning() -> None:
    """Bold subtracts 1 from danger and wary adds 1. Holding both is neutral.

    Precedence would mean the order the tags were declared in silently decided
    the outcome, which is exactly the kind of rule nobody can debug later.
    """
    weights = weights_for(library(profiles=(CreatureProfile("cinder-hound", traits=(BOLD, WARY)),)))

    assert weights["danger"] == unmodified()["danger"]


def test_composition_does_not_depend_on_the_order_traits_were_authored_in() -> None:
    one = weights_for(library(profiles=(CreatureProfile("cinder-hound", traits=(BOLD, WARY)),)))
    other = weights_for(library(profiles=(CreatureProfile("cinder-hound", traits=(WARY, BOLD)),)))

    assert one == other


def test_weights_are_clamped_rather_than_allowed_to_run_away() -> None:
    piled_on = library(
        profiles=(CreatureProfile("cinder-hound", {"danger": MAX_WEIGHT}, traits=(WARY,)),),
        unit_behaviors=(UnitBehavior("north-t0-u1", traits=(WARY,)),),
    )

    assert weights_for(piled_on)["danger"] == MAX_WEIGHT


def test_a_weight_driven_below_zero_stops_at_zero_rather_than_inverting() -> None:
    weights = weights_for(
        library(profiles=(CreatureProfile("cinder-hound", {"danger": 0.5}, traits=(BOLD,)),))
    )

    assert weights["danger"] == 0.0


# --- personality strength ---------------------------------------------------


def test_an_omitted_strength_falls_back_to_the_definition_s_default() -> None:
    explicit = weights_for(
        library(
            mage_personalities=(MagePersonality("north-t0-u0", (PersonalityRef(CAREFUL, strength=0.5),)),)
        )
    )
    implied = weights_for(
        library(mage_personalities=(MagePersonality("north-t0-u0", (PersonalityRef(CAREFUL),)),))
    )

    assert implied == explicit
    assert implied["danger"] == unmodified()["danger"] + 0.5


def test_strength_scales_the_contribution() -> None:
    def danger_at(strength: float) -> float:
        return weights_for(
            library(
                mage_personalities=(
                    MagePersonality("north-t0-u0", (PersonalityRef(CAREFUL, strength=strength),)),
                )
            )
        )["danger"]

    base = unmodified()["danger"]

    assert danger_at(0.5) == base + 0.5
    assert danger_at(1.0) == base + 1.0
    assert danger_at(2.0) == base + 2.0


def test_strength_zero_means_no_opinion_and_never_the_opposite_one() -> None:
    """A reckless mage dialled to zero is a mage with nothing to say about risk.

    The tempting reading — that zero flips it to cautious — would make the dial
    non-monotonic, so turning a personality down would eventually turn it into
    its own opposite.
    """
    silent = weights_for(
        library(
            mage_personalities=(MagePersonality("north-t0-u0", (PersonalityRef(RECKLESS, strength=0.0),)),)
        )
    )

    assert silent == weights_for(library())


def test_a_mage_s_personality_reaches_the_summons_of_its_own_troop() -> None:
    weights = weights_for(
        library(mage_personalities=(MagePersonality("north-t0-u0", (PersonalityRef(RECKLESS),)),))
    )

    assert weights["danger"] == unmodified()["danger"] - 1.0


def test_two_mages_with_the_same_tag_sum_their_strength_and_then_clamp() -> None:
    """More reckless, not twice as reckless — the ceiling is what bounds this."""
    index = index_library(
        library(
            mage_personalities=(
                MagePersonality("m0", (PersonalityRef(CAREFUL, strength=1.5),)),
                MagePersonality("m1", (PersonalityRef(CAREFUL, strength=1.5),)),
            )
        ),
        CATALOG,
    )
    refs = personality_refs_for_troop("north-t0", ["m0", "m1"], index)
    unit = make_unit("s0", HOUND, "north", HERE)

    resolved = resolve_behavior(unit, capabilities_of(unit), index, refs)

    assert [(p.tag, p.strength) for p in resolved.personalities] == [(CAREFUL, MAX_STRENGTH)]
    # Both references survive the summation, each with its own strength.
    assert [(s.mage_id, s.strength) for s in resolved.personalities[0].sources] == [
        ("m0", 1.5),
        ("m1", 1.5),
    ]


def test_resolved_personalities_are_reported_for_diagnostics() -> None:
    world = make_world([make_unit("north-t0-u0", ADEPT, "north", HERE)])
    attach(
        world,
        library(
            mage_personalities=(MagePersonality("north-t0-u0", (PersonalityRef(RECKLESS, strength=1.25),)),)
        ),
        [ADEPT],
    )

    assert world.units[0].ai is not None
    resolved = world.units[0].ai.behavior.personalities
    assert [(p.tag, p.strength) for p in resolved] == [(RECKLESS, 1.25)]
    assert not defaulted(resolved[0])


# --- validation -------------------------------------------------------------


def test_a_profile_for_a_creature_not_in_the_battle_is_rejected() -> None:
    with pytest.raises(ValueError, match="not in the unit type catalog"):
        index_library(library(profiles=(CreatureProfile("dire-wombat"),)), CATALOG)


def test_an_undefined_trait_is_rejected() -> None:
    with pytest.raises(ValueError, match="trait 'glorious', which is not defined"):
        index_library(
            library(profiles=(CreatureProfile("cinder-hound", traits=(TraitTag("glorious"),)),)), CATALOG
        )


def test_an_unknown_factor_is_rejected() -> None:
    with pytest.raises(ValueError, match="which is not a factor"):
        index_library(
            BehaviorLibrary(traits=(TraitDefinition(BOLD, {"vibes": 1.0}),)),  # type: ignore[dict-item]
            CATALOG,
        )


def test_a_strength_outside_the_range_is_rejected() -> None:
    with pytest.raises(ValueError, match=f"strength runs 0.0 to {MAX_STRENGTH}"):
        index_library(
            library(mage_personalities=(MagePersonality("m0", (PersonalityRef(RECKLESS, strength=9.0),)),)),
            CATALOG,
        )


def test_a_negative_strength_is_rejected_rather_than_inverting_a_personality() -> None:
    with pytest.raises(ValueError, match="strength runs"):
        index_library(
            library(mage_personalities=(MagePersonality("m0", (PersonalityRef(RECKLESS, strength=-1.0),)),)),
            CATALOG,
        )


def test_the_same_personality_twice_on_one_mage_is_rejected() -> None:
    with pytest.raises(ValueError, match="twice"):
        index_library(
            library(
                mage_personalities=(
                    MagePersonality("m0", (PersonalityRef(RECKLESS), PersonalityRef(RECKLESS, strength=2.0))),
                )
            ),
            CATALOG,
        )


def test_adding_and_removing_the_same_trait_is_rejected() -> None:
    with pytest.raises(ValueError, match="two minds"):
        index_library(
            library(unit_behaviors=(UnitBehavior("u0", traits=(BOLD,), removed_traits=(BOLD,)),)),
            CATALOG,
        )


def test_a_trait_needing_a_capability_the_creature_lacks_is_a_clear_error() -> None:
    """The sharpshooter trait on something that cannot shoot. Caught at build.

    This is the line the ticket draws: capabilities decide what is possible and
    traits only decide what is preferred, so a preference that presumes a
    capability is a data error, not a preference that quietly does nothing.
    """
    world = make_world([make_unit("north-t0-u0", HOUND, "north", HERE, troop_id="north-t0")])
    world.troops[0].mage_ids.append("north-t0-u0")

    with pytest.raises(ValueError, match="lacks ranged_attack"):
        attach_behavior(
            world.units,
            world.troops,
            library(profiles=(CreatureProfile("cinder-hound", traits=(SHARPSHOOTER,)),)),
            CATALOG,
        )


def test_a_personality_on_a_summon_is_rejected() -> None:
    world = make_world([make_unit("north-t0-u0", HOUND, "north", HERE)])

    with pytest.raises(ValueError, match="which is a summon"):
        attach_behavior(
            world.units,
            world.troops,
            library(mage_personalities=(MagePersonality("north-t0-u0", (PersonalityRef(RECKLESS),)),)),
            CATALOG,
        )


def test_data_naming_a_unit_that_is_not_in_the_battle_is_rejected() -> None:
    world = make_world([make_unit("north-t0-u0", ADEPT, "north", HERE)])

    with pytest.raises(ValueError, match="not in this battle"):
        attach_behavior(
            world.units,
            world.troops,
            library(unit_behaviors=(UnitBehavior("nobody", traits=(BOLD,)),)),
            CATALOG,
        )


# --- the snapshot cost ------------------------------------------------------


def test_resolved_behavior_is_shared_rather_than_copied_into_every_snapshot() -> None:
    """`run_battle` deep-copies the world once a tick; this is immutable."""
    world = make_world([make_unit("north-t0-u0", ADEPT, "north", HERE)])
    attach(world, library(profiles=(CreatureProfile("ember-adept"),)), [ADEPT])
    assert world.units[0].ai is not None

    behavior = world.units[0].ai.behavior

    assert copy.deepcopy(behavior) is behavior
    assert copy.deepcopy(world).units[0].ai.behavior is behavior  # type: ignore[union-attr]
